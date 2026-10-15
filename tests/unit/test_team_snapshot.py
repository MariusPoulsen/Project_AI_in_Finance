"""Portable fixture handoff only: no actual-study acceptance or external sources."""

import zipfile
from datetime import date
from importlib.metadata import version
from io import BytesIO

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from streamlit.testing.v1 import AppTest
from test_primary_research import promote
from test_primary_research import release as release
from xgboost import XGBClassifier

from structural_break.collaboration import queries
from structural_break.collaboration.cli import main
from structural_break.collaboration.queries import backtest_inputs, existing_predictions
from structural_break.collaboration.snapshot import (
    _development_file,
    check_snapshot,
    export_snapshot,
    import_snapshot,
)
from structural_break.config.paths import ProjectPaths
from structural_break.ml.model import SigmoidCalibrator
from structural_break.research.evaluation import ResearchModel
from structural_break.research.primary import MODEL_NAMES, PrimaryNotReadyError, read_json
from structural_break.research.protocol import canonical_bytes
from structural_break.services.research_app import PrimaryResearchService
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file, write_bytes


@pytest.fixture
def accepted_team(release):
    """Extend the existing synthetic publication fixture with usable small tables.

    Native models are really fitted/reloaded here; source/report acceptance is
    the existing explicit engineering stub, never a real-study result.
    """
    paths, receipt_path, receipt, _ = release
    factory = DuckDBConnectionFactory(paths.database)
    registry_path = paths.artifacts / "research" / receipt["registry_version"] / "manifest.json"
    registry = read_json(registry_path)
    events = pd.DataFrame(
        {
            "event_id": [f"fixture-{i}" for i in range(4)],
            "event_date": [date(2022, 1, 3)] * 4,
            "pair_id": ["A__B"] * 4,
            "leg_a": ["A"] * 4,
            "leg_b": ["B"] * 4,
            "business_group": ["fixture"] * 4,
            "baseline1_eligible": [True, False, True, False],
            "research_partition": ["assessment"] * 4,
        }
    )
    inputs = events.assign(q=[-2.0, -1.0, 1.0, 2.0])
    x, y = inputs[["q"]], np.array([0, 0, 1, 1])
    native = {
        "logistic": ResearchModel(
            ("q",),
            LogisticRegression().fit(x, y),
            SigmoidCalibrator(1, 0, 4, 2, "fixture"),
            "logistic",
        ),
        "xgboost": ResearchModel(
            ("q",),
            XGBClassifier(n_estimators=2, max_depth=1, n_jobs=1).fit(x, y),
            SigmoidCalibrator(1, 0, 4, 2, "fixture"),
            "xgboost",
        ),
    }

    def frame(directory, name, rows):
        path = directory / (name + ".parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        rows.to_parquet(path, index=False)
        return {"name": name, "path": path.name, "sha256": sha256_file(path), "rows": len(rows)}

    def save_registration(path, manifest):
        write_bytes(path, canonical_bytes(manifest), replace=True)
        with factory.connect(read_only=False) as connection:
            connection.execute(
                "UPDATE analytics.research_versions SET checksum=? WHERE research_version=?",
                [sha256_file(path), manifest["research_version"]],
            )

    roster = pd.DataFrame({"pair_id": ["A__B"], "leg_a": ["A"], "leg_b": ["B"]})
    prices = pd.DataFrame(
        {"ticker": ["A", "B"], "trading_date": [date(2022, 1, 3)] * 2, "adj_close": [10.0, 20.0]}
    )
    registry["inputs"] = []
    for role in ("universe", "market"):
        directory = paths.workspace_root / role / "fixture"
        items = [frame(directory, "pair_universe", roster)]
        if role == "market":
            items.append(frame(directory, "prices", prices))
            raw = directory / "raw/VIX_History.csv"
            write_bytes(raw, b"DATE,CLOSE\n2026-01-02,20\n")
            items.append({"path": "raw/VIX_History.csv", "sha256": sha256_file(raw)})
        manifest_path = directory / "manifest.json"
        write_bytes(
            manifest_path, canonical_bytes({"files": {i["path"]: i["sha256"] for i in items}})
        )
        registry["inputs"].append(
            {
                "role": role,
                "path": manifest_path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(manifest_path),
            }
        )
    registry["files"] = []
    pair_directory = registry_path.parent / "pairs/A__B"
    pair_files = []
    for name in ("relationship_snapshots", "daily_pair_state", "raw_crossings"):
        pair_files.append(
            frame(
                pair_directory,
                name,
                pd.DataFrame({"pair_id": ["A__B"], "trading_date": [date(2022, 1, 3)]}),
            )
        )
    for horizon in (20, 10, 30):
        for suffix, rows in (
            ("events", events),
            ("features", inputs),
            ("targets", events[["event_id"]].assign(y_revert_success=y)),
            ("partitions", events[["event_id", "research_partition"]]),
        ):
            name = f"h{horizon}_{suffix}"
            registry["files"].append(frame(registry_path.parent, name, rows))
            pair_files.append(frame(pair_directory, name, rows))
    pair_path = pair_directory / "manifest.json"
    write_bytes(pair_path, canonical_bytes({"pair_id": "A__B", "files": pair_files}))
    registry["pair_manifests"] = [{"pair_id": "A__B", "sha256": sha256_file(pair_path)}]
    funnel = registry_path.parent / "funnel.json"
    write_bytes(funnel, canonical_bytes({"final_test_read": False}))
    registry["funnel_sha256"] = sha256_file(funnel)
    registry["final_test_read"] = False
    save_registration(registry_path, registry)
    for generation in receipt["completed_generations"]:
        directory = paths.artifacts / "research" / generation["research_version"]
        path = directory / "manifest.json"
        evaluation = read_json(path)
        stored = events.assign(y_revert_success=y)
        for name in sorted(MODEL_NAMES):
            model = native[name.split("_", 1)[0]]
            output = BytesIO()
            joblib.dump(model, output)
            model_path = directory / "models" / (name + ".joblib")
            write_bytes(model_path, output.getvalue(), replace=True)
            next(item for item in evaluation["model_files"] if item["name"] == name)["sha256"] = (
                sha256_file(model_path)
            )
            stored[name + "_raw"] = model.estimator.predict_proba(x)[:, 1]
            stored[name + "_calibrated"] = model.predict(inputs)
        evaluation["files"] = [
            frame(directory, "predictions", stored),
            frame(directory, "model_inputs", inputs),
        ]
        evaluation["identity_inputs"]["registry_manifest_sha256"] = sha256_file(registry_path)
        evaluation["identity_inputs"]["computation"]["libraries"] = {"numpy": version("numpy")}
        report_path = directory / "report.json"
        report = read_json(report_path)
        report["cohorts"] = {"assessment": {"n": 4, "positives": 2, "ACTIVE": 2}}
        report["text_coverage"] = {"assessment": {"n": 4, "flags": {}}}
        for variants in report["models"].values():
            for model_report in variants.values():
                model_report["calibrated_assessment"].update(n=4, positives=2)
                model_report["calibrated_assessment_slices"]["ACTIVE"]["True"].update(
                    n=2, positives=1
                )
        write_bytes(report_path, canonical_bytes(report), replace=True)
        evaluation["report_sha256"] = sha256_file(report_path)
        save_registration(path, evaluation)
        generation["manifest_sha256"] = sha256_file(path)
    write_bytes(receipt_path, canonical_bytes(receipt), replace=True)
    primary = promote(paths, receipt_path)
    (paths.workspace_root / "cache/data/raw/sec/filings").mkdir(parents=True)
    (paths.workspace_root / "cache/data/raw/sec/filings/secret-source.txt").write_text(
        "not included"
    )
    (paths.workspace_root / ".env").write_text("not included")
    return paths, primary


def imported_app(service):
    from app.streamlit_app import main

    main(service)


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
@pytest.mark.usefixtures("preserve_main_module")
def test_round_trip_app_sql_native_inference_and_backtest_inputs(accepted_team, tmp_path):
    original, primary = accepted_team
    archive = tmp_path / "shared.zip"
    exported = export_snapshot(original, archive)
    with zipfile.ZipFile(archive) as zipped:
        assert not any(
            "cache/" in name or "/events/" in name or "/raw/" in name or name.endswith(".env")
            for name in zipped.namelist()
        )
    workspace = tmp_path / "colleague Ø with spaces" / "data"
    imported = import_snapshot(
        original.project_root, archive, workspace, expected_sha256=exported["sha256"]
    )
    assert imported["primary_version"] == primary["primary_version"]
    paths = ProjectPaths.resolve(original.project_root, workspace)
    assert check_snapshot(paths)["final_test_unlocked"] is False
    view = PrimaryResearchService(paths).view()
    assert len(PrimaryResearchService(paths).comparison(view, 20)) == 10
    app = AppTest.from_function(
        imported_app, args=(PrimaryResearchService(paths),), default_timeout=30
    ).run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Structural-Break Research v2"
    assert app.sidebar.selectbox[0].value == primary["primary_version"]
    assert app.dataframe[0].value["n"].tolist() == [4] * 10
    app.sidebar.radio[0].set_value("Event scores").run()
    assert not app.exception and not app.error
    assert len(app.dataframe[0].value) == 4
    assert "y_revert_success" not in app.dataframe[0].value
    for horizon in (20, 10, 30):
        predictions, result = existing_predictions(
            paths, horizon=horizon, models=tuple(sorted(MODEL_NAMES))
        )
        assert len(predictions) == 4 and max(result["native_max_errors"].values()) <= 1e-12
        assert "y_revert_success" not in predictions
        assert predictions["baseline1_eligible"].tolist() == [True, False, True, False]
    frames = backtest_inputs(paths, "A__B")
    assert len(frames["prices"]) == 2 and len(frames["predictions"]) == 4
    version = view.evaluations[20].rsplit("_", 1)[-1]
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert (
            connection.execute(
                f"SELECT count(*) FROM analytics.research_evaluation_predictions_{version}"
            ).fetchone()[0]
            == 4
        )
    assert (
        import_snapshot(
            original.project_root, archive, workspace, expected_sha256=exported["sha256"]
        )["status"]
        == "ALREADY_IMPORTED"
    )


def test_import_rejects_wrong_external_hash_and_preserves_existing_data(accepted_team, tmp_path):
    paths, _ = accepted_team
    archive = tmp_path / "shared.zip"
    exported = export_snapshot(paths, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("original")
    with pytest.raises(ValueError, match="SHA-256"):
        import_snapshot(paths.project_root, archive, tmp_path / "fresh", expected_sha256="0" * 64)
    with pytest.raises(FileExistsError, match="never overwritten"):
        import_snapshot(
            paths.project_root, archive, destination, expected_sha256=exported["sha256"]
        )
    assert sentinel.read_text() == "original"


def test_tampered_native_model_is_rejected_before_deserialization(accepted_team, monkeypatch):
    paths, primary = accepted_team
    monkeypatch.setattr(joblib, "load", lambda *_: pytest.fail("Unverified model deserialized"))
    version = primary["identity_inputs"]["evaluations"]["20"]["research_version"]
    (paths.artifacts / "research" / version / "models/logistic_A.joblib").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        existing_predictions(paths)


def test_corrupted_payload_and_unexpected_archive_paths_never_import(accepted_team, tmp_path):
    paths, _ = accepted_team
    archive = tmp_path / "shared.zip"
    export_snapshot(paths, archive)
    for corruption in ("payload", "traversal"):
        changed = tmp_path / (corruption + ".zip")
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(changed, "w") as target:
            altered = False
            for entry in source.infolist():
                body = source.read(entry)
                if (
                    corruption == "payload"
                    and entry.filename.startswith("workspace/")
                    and not altered
                ):
                    body = bytes([body[0] ^ 1]) + body[1:]
                    altered = True
                target.writestr(entry.filename, body)
            if corruption == "traversal":
                target.writestr("workspace/../../escaped.txt", "never extracted")
        workspace = tmp_path / (corruption + "-workspace")
        with pytest.raises(ValueError, match="checksum|unexpected files"):
            import_snapshot(
                paths.project_root, changed, workspace, expected_sha256=sha256_file(changed)
            )
        assert not workspace.exists() and not (tmp_path / "escaped.txt").exists()


def test_cli_outputs_are_external_and_imported_data_is_checked(accepted_team, tmp_path, capsys):
    paths, _ = accepted_team
    archive = tmp_path / "shared.zip"
    exported = export_snapshot(paths, archive)
    workspace = tmp_path / "new-group-workspace"
    import_snapshot(paths.project_root, archive, workspace, expected_sha256=exported["sha256"])
    options = ["--project-root", str(tmp_path), "--workspace-root", str(workspace)]
    # Project metadata/migrations are only needed during import, not offline reading.
    assert main(["predict", *options, "--pair", "A__B"]) == 0
    outputs = list((tmp_path / "outputs").glob("predict_*.csv"))
    assert len(outputs) == 1 and len(pd.read_csv(outputs[0])) == 4
    assert main(["predict", *options, "--output", str(workspace / "overwrite.csv")]) == 1
    assert not (workspace / "overwrite.csv").exists()
    assert (
        main(["backtest-inputs", *options, "--pair", "A__B", "--output", str(tmp_path / "bt")]) == 0
    )
    assert len(list((tmp_path / "bt").glob("*.parquet"))) == 9
    roster = workspace / "market/fixture/pair_universe.parquet"
    roster.write_bytes(b"altered roster")
    with pytest.raises(ValueError, match="roster checksum"):
        backtest_inputs(ProjectPaths.resolve(paths.project_root, workspace), "A__B")
    assert main(["check", *options]) == 1
    assert '"status": "FAILED"' in capsys.readouterr().out


def test_native_inference_requires_original_libraries(accepted_team, monkeypatch):
    paths, _ = accepted_team
    monkeypatch.setattr(queries, "version", lambda _: "different-version")
    with pytest.raises(ValueError, match="original locked numerical libraries"):
        existing_predictions(paths)


def test_snapshot_date_guard_rejects_final_test_observations(tmp_path):
    path = tmp_path / "outcomes.parquet"
    pd.DataFrame({"event_date": [date(2024, 1, 2)]}).to_parquet(path)
    with pytest.raises(ValueError, match="final-test observations"):
        _development_file(path, "2023-12-31")


def test_export_requires_a_real_registered_primary(paths, tmp_path):
    with pytest.raises(PrimaryNotReadyError):
        export_snapshot(paths, tmp_path / "unfinished.zip")
    assert not (tmp_path / "unfinished.zip").exists()
