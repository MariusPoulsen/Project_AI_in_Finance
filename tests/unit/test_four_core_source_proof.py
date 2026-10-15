"""Execution-mode receipts and CLI restrictions for full four-core source proofs."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_source_proof import source_fixture as source_fixture

from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths
from structural_break.research import cli, intelligence, source_proof
from structural_break.research.protocol import canonical_bytes, identity
from structural_break.storage.files import sha256_file, write_bytes


def test_four_core_receipt_records_execution_and_preserves_scientific_scope(
    source_fixture: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, directory, _, calls = source_fixture
    reconstruct = intelligence.verify_event_intelligence
    delegated: list[dict[str, Any]] = []

    def observed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        delegated.append(kwargs)
        return reconstruct(*args, **kwargs)

    monkeypatch.setattr(intelligence, "verify_event_intelligence", observed)
    serial = source_proof.mint_source_proof(
        paths, "registry", directory, purpose="fitting_input", event_workers=0
    )
    parallel = source_proof.mint_source_proof(
        paths, "registry", directory, purpose="fitting_input", event_workers=4
    )
    assert len(calls) == 2
    assert [row["event_workers"] for row in delegated] == [0, 4]
    assert all(row["cache_workspace"] == paths.workspace_root / "cache" for row in delegated)
    serial_proof = json.loads(Path(serial["source_proof_path"]).read_bytes())
    parallel_proof = json.loads(Path(parallel["source_proof_path"]).read_bytes())
    assert parallel["event_workers"] == parallel_proof["event_workers"] == 4
    assert serial["event_workers"] == serial_proof["event_workers"] == 0
    assert serial_proof["identity_inputs"] == parallel_proof["identity_inputs"]
    assert serial["source_proof_sha256"] != parallel["source_proof_sha256"]
    assert parallel_proof["initial_parser_cache_empty"] is True
    assert parallel_proof["builder_parser_cache_used"] is False
    assert parallel_proof["complete_raw_reconstruction"] is True
    assert parallel_proof["final_test_read"] is False
    for result in (serial, parallel):
        assert (
            source_proof.validate_source_proof(
                paths,
                "registry",
                directory,
                Path(result["source_proof_path"]),
                result["source_proof_sha256"],
                purpose="fitting_input",
            )["event_workers"]
            == result["event_workers"]
        )


@pytest.mark.parametrize("workers", [2, True, False])
def test_invalid_mint_mode_is_rejected_before_scope_or_source_replay(
    source_fixture: Any, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    paths, directory, _, calls = source_fixture

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Invalid mode must fail before inspecting scope or replaying sources")

    monkeypatch.setattr(source_proof, "_scope", forbidden)
    with pytest.raises(ValueError, match="worker|mode"):
        source_proof.mint_source_proof(
            paths, "registry", directory, purpose="fitting_input", event_workers=workers
        )
    assert calls == []


@pytest.mark.parametrize("workers", [2, True, "4", None])
def test_self_resealed_synthetic_receipt_cannot_bless_invalid_execution_mode(
    source_fixture: Any, workers: Any
) -> None:
    paths, directory, _, _ = source_fixture
    original = source_proof.mint_source_proof(
        paths, "registry", directory, purpose="fitting_input", event_workers=4
    )
    unsigned = json.loads(Path(original["source_proof_path"]).read_bytes())
    unsigned.pop("source_verification_version")
    unsigned["event_workers"] = workers
    version = "research_source_verification_" + identity(unsigned)[:24]
    # This is a new synthetic fixture receipt at its matching content-addressed
    # path. No registered artifact or production proof is rewritten.
    forged = {**unsigned, "source_verification_version": version}
    proof_path = write_bytes(
        paths.artifacts / "source_verification" / version / "manifest.json",
        canonical_bytes(forged),
    )
    with pytest.raises(ValueError, match="scope, full reconstruction or purpose differs"):
        source_proof.validate_source_proof(
            paths,
            "registry",
            directory,
            proof_path,
            sha256_file(proof_path),
            purpose="fitting_input",
        )


@pytest.mark.parametrize(
    "command", [item for item in cli._COMMANDS if item != "verify-source-inputs"]
)
def test_cli_four_event_workers_are_restricted_to_complete_source_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_root: Path, command: str
) -> None:
    args = cli._parser().parse_args([command, "--event-workers", "4"])

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Invalid event-worker routing must fail before loading scientific inputs")

    monkeypatch.setattr(cli, "load_protocol", forbidden)
    with pytest.raises(ValueError, match="restricted to complete source verification"):
        cli.run_command(
            args,
            ProjectPaths(project_root, tmp_path / "workspace"),
            RuntimeSettings(_env_file=None),
        )


@pytest.mark.parametrize("workers", ["2", "-1", "true"])
def test_cli_worker_choices_are_zero_or_four(workers: str) -> None:
    with pytest.raises(SystemExit) as error:
        cli._parser().parse_args(["verify-source-inputs", "--event-workers", workers])
    assert error.value.code == 2


def test_cli_success_reports_the_actual_four_core_execution_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[dict[str, Any]] = []

    def mint(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return {
            "source_verification_version": "synthetic-fixture-proof",
            "event_workers": kwargs["event_workers"],
            "event_count": 8,
            "complete_raw_reconstruction": True,
            "final_test_read": False,
        }

    monkeypatch.setattr(source_proof, "mint_source_proof", mint)
    monkeypatch.setattr(cli, "RuntimeSettings", lambda **kwargs: RuntimeSettings(_env_file=None))
    assert (
        cli.main(
            [
                "verify-source-inputs",
                "--project-root",
                str(project_root),
                "--workspace-root",
                str(tmp_path / "workspace"),
                "--registry-version",
                "registry",
                "--event-workers",
                "4",
            ]
        )
        == 0
    )
    assert len(seen) == 1 and seen[0]["event_workers"] == 4
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert rows[-1]["status"] == "SUCCESS" and rows[-1]["event_workers"] == 4
    assert rows[-1]["complete_raw_reconstruction"] is True
    assert rows[-1]["final_test_read"] is False
