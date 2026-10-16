"""Freeze manifest, validation-decision checklist and the explicit final-test unlock gate.

Accepted bindings here are test stand-ins on the synthetic registered workspace;
production bindings come only from `bind_accepted`/`load_primary`.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from structural_break.backtest import cli
from structural_break.backtest.freeze import (
    UNLOCK_STATEMENT,
    FreezeManifest,
    build_freeze_manifest,
    require_final_test_unlock,
    run_acceptance,
)
from structural_break.backtest.historical import HistoricalSources, bind_unaccepted
from structural_break.backtest.historical_experiment import (
    run_historical_experiment,
    verify_historical_experiment,
)
from structural_break.research.primary import PrimaryNotReadyError
from tests.historical_workspace import make_workspace_horizons

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
PRIMARY = "research_primary_" + "c" * 24


def _opener(root: Path, horizons: tuple[int, ...]) -> dict[int, HistoricalSources]:
    chains = make_workspace_horizons(root, horizons)
    opened = {}
    for horizon, (relative, sha) in chains.items():
        binding = bind_unaccepted(root, relative, sha).model_copy(
            update={"acceptance": "ACCEPTED", "primary_version": PRIMARY}
        )
        opened[horizon] = HistoricalSources(root, binding)
    return opened


@pytest.fixture(scope="module")
def accepted_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    base = tmp_path_factory.mktemp("acceptance")
    sources = _opener(base / "workspace", (10, 20, 30))
    return run_acceptance(sources.__getitem__, CONFIGS, base / "out")


def _unlock(directory: Path, freeze: Path, *, statement: str = UNLOCK_STATEMENT) -> Path:
    manifest = FreezeManifest.model_validate_json(freeze.read_bytes())
    path = directory / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "p6-final-test-unlock-v1",
                "freeze_manifest_sha256": hashlib.sha256(freeze.read_bytes()).hexdigest(),
                "freeze_id": manifest.freeze_id,
                "authorized_by": "repository-owner",
                "authorized_at": datetime(2026, 10, 16, 12, tzinfo=UTC).isoformat(),
                "statement": statement,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_acceptance_run_verifies_every_horizon_and_freezes_the_method(
    accepted_run: dict[str, object],
) -> None:
    assert accepted_run["status"] == "ACCEPTANCE_RUN_COMPLETE"
    assert accepted_run["final_test_unlocked"] is False and accepted_run["full_system"] == "NOT_RUN"
    horizons = accepted_run["horizons"]
    assert isinstance(horizons, dict) and set(horizons) == {"10", "20", "30"}
    assert all(
        entry["verification"]["status"] == "VERIFIED_HISTORICAL_REPLAY"
        for entry in horizons.values()
    )
    freeze = FreezeManifest.model_validate_json(
        Path(str(accepted_run["freeze_manifest"])).read_bytes()
    )
    assert freeze.all_decisions_closed and freeze.open_decisions == ()
    assert freeze.final_test_unlocked is False and freeze.final_test_read is False
    identity = freeze.identity
    assert [item.horizon_sessions for item in identity.horizons] == [10, 20, 30]
    assert identity.primary_version == PRIMARY and identity.controller == "DEFERRED_NOT_RUN"
    h20 = identity.horizons[1]
    assert h20.trading_thresholds == (0.3, 0.2, 0.4, 0.65)
    assert h20.combinations_n == 25 and len(h20.execution_policy_versions) == 22
    assert identity.horizons[0].execution_policy_versions == (
        "phase6-execution-v2-20261016:horizon=10",
    )
    assert h20.feature_schema_version == "features-fixture-v1"
    statuses = {item.name: item.status for item in identity.decisions}
    assert statuses["full_system_controller"] == "DEFERRED"
    assert {item.name for item in identity.config_files} == {
        "phase6_execution.json",
        "phase6_execution_sensitivities.json",
        "phase6_analysis.json",
    }


def test_final_test_unlock_requires_the_owner_record_for_this_exact_freeze(
    accepted_run: dict[str, object], tmp_path: Path
) -> None:
    freeze = Path(str(accepted_run["freeze_manifest"]))
    with pytest.raises(PermissionError, match="no owner unlock record"):
        require_final_test_unlock(freeze, None)
    with pytest.raises(ValidationError, match="verbatim"):
        require_final_test_unlock(freeze, _unlock(tmp_path, freeze, statement="yes"))
    unlock = _unlock(tmp_path, freeze)
    assert require_final_test_unlock(freeze, unlock).freeze_id == freeze.parent.name
    value = json.loads(unlock.read_text(encoding="utf-8"))
    value["freeze_manifest_sha256"] = "0" * 64
    unlock.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PermissionError, match="different freeze manifest"):
        require_final_test_unlock(freeze, unlock)


def test_partial_acceptance_keeps_an_open_decision_and_the_lock(tmp_path: Path) -> None:
    sources = _opener(tmp_path / "workspace", (20,))[20]
    manifest = run_historical_experiment(sources, CONFIGS, tmp_path / "out")
    verification = verify_historical_experiment(manifest, sources, CONFIGS)
    freeze = build_freeze_manifest([(manifest, sources, verification)], CONFIGS, tmp_path / "out")
    loaded = FreezeManifest.model_validate_json(freeze.read_bytes())
    assert loaded.open_decisions == ("accepted_development_experiments",)
    with pytest.raises(PermissionError, match="open decisions accepted_development_experiments"):
        require_final_test_unlock(freeze, _unlock(tmp_path, freeze))


def test_freeze_refuses_unverified_or_mixed_generations(tmp_path: Path) -> None:
    sources = _opener(tmp_path / "a", (20,))[20]
    manifest = run_historical_experiment(sources, CONFIGS, tmp_path / "out")
    with pytest.raises(ValueError, match="independently verified"):
        build_freeze_manifest([(manifest, sources, {"status": "NO"})], CONFIGS, tmp_path / "out")
    verification = verify_historical_experiment(manifest, sources, CONFIGS)
    other = _opener(tmp_path / "b", (10,))[10]
    other_manifest = run_historical_experiment(other, CONFIGS, tmp_path / "out")
    other_verification = verify_historical_experiment(other_manifest, other, CONFIGS)
    with pytest.raises(ValidationError, match="same accepted generations"):
        build_freeze_manifest(
            [(manifest, sources, verification), (other_manifest, other, other_verification)],
            CONFIGS,
            tmp_path / "out",
        )


def test_cli_gate_reports_locked_and_acceptance_needs_a_publication(
    accepted_run: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = ["structural-break-backtest", "final-test-gate", "--freeze-manifest"]
    monkeypatch.setattr(sys, "argv", [*gate, str(accepted_run["freeze_manifest"])])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert json.loads(capsys.readouterr().out)["final_test_unlocked"] is False
    make_workspace_horizons(tmp_path / "workspace", (20,))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "structural-break-backtest",
            "p6-acceptance",
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    with pytest.raises(PrimaryNotReadyError):
        cli.main()
