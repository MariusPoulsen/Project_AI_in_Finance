"""The offline two-pair source freeze -> causal engines -> independent research DB."""

import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from structural_break.config.loader import load_config
from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths
from structural_break.data.http import FetchedResponse
from structural_break.data.market import VIX_URL, session_schedule
from structural_break.ml.fixtures import fixture_inputs
from structural_break.research import runner
from structural_break.research.cli import evidence_events
from structural_break.research.intelligence import build_event_intelligence, collect_sec_metadata
from structural_break.research.market import collect_market
from structural_break.research.model_job import train_research_models, verify_research_models
from structural_break.research.protocol import load_protocol
from structural_break.research.universe import freeze_universe
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    original = Path(__file__).resolve().parents[2]
    base = tmp_path_factory.mktemp("research_runner")
    project = base / "project"
    project.mkdir()
    # Keep computation hashes stable while the real working tree is being edited.
    for name in ("src", "configs", "sql"):
        shutil.copytree(original / name, project / name)
    shutil.copyfile(original / "pyproject.toml", project / "pyproject.toml")
    paths = ProjectPaths.resolve(project, base / "workspace")
    roster = yaml.safe_load((project / "configs/research_v2_universe.yaml").read_text("utf-8"))
    roster["groups"] = [
        {**roster["groups"][0], "tickers": ["KO", "PEP"]},
        {**roster["groups"][3], "tickers": ["HD", "LOW"]},
    ]
    roster["issuer_rules"] = {}
    roster_path = project / "configs/test_roster.yaml"
    roster_path.write_text(yaml.safe_dump(roster), encoding="utf-8")
    original_config = load_config(project / "configs").model_dump(mode="json")
    original_config["universe"]["pairs"] = original_config["universe"]["pairs"][:2]
    config = ProjectConfig.model_validate(original_config)
    source_directory = json.dumps(
        {
            str(index): {"ticker": ticker, "cik_str": 9000000 + index, "title": f"Fixture {ticker}"}
            for index, ticker in enumerate(("KO", "PEP", "HD", "LOW"))
        }
    ).encode()
    universe = paths.data / "research/universe"
    freeze_universe(roster_path, config, source_directory, universe)
    protocol = load_protocol(project / "configs/research_v2.yaml").model_dump(mode="json")
    protocol.update(
        data_start="2014-01-01",
        development_end="2018-12-31",
        fit_start="2015-01-01",
        fit_end="2016-12-31",
        tuning_years=[2016],
        calibration_start="2017-01-01",
        calibration_end="2017-12-31",
        assessment_start="2018-01-01",
        assessment_end="2018-12-31",
        formation_sessions=252,
        logistic_c=[0.1],
        xgb_candidates=[
            {"max_depth": 1, "n_estimators": 5, "learning_rate": 0.1, "min_child_weight": 1}
        ],
        bootstrap_replicates=100,
    )
    protocol_path = project / "configs/test_protocol.yaml"
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    prices = fixture_inputs()[0]
    xly = prices.loc[prices.ticker.eq("XLP")].copy()
    xly["ticker"] = "XLY"
    prices = pd.concat([prices, xly], ignore_index=True)

    def download(tickers, **kwargs):
        frame = prices.loc[prices.ticker.eq(tickers[0])].copy()
        lower = date.fromisoformat(kwargs["start"])
        upper = date.fromisoformat(kwargs["end"])
        frame = frame.loc[frame.trading_date.ge(lower) & frame.trading_date.lt(upper)]
        frame = frame.set_index(pd.DatetimeIndex(frame.trading_date))
        frame = frame[["open", "high", "low", "close", "adj_close", "volume"]].rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "adj_close": "Adj Close",
                "volume": "Volume",
            }
        )
        frame["Dividends"] = 0.0
        frame["Stock Splits"] = 0.0
        return frame

    def get(url):
        assert url == VIX_URL
        days = session_schedule(date(2013, 12, 20), date(2018, 12, 31))["trading_date"]
        csv = (
            pd.DataFrame(
                {
                    "DATE": [day.strftime("%m/%d/%Y") for day in days],
                    "OPEN": 20.0,
                    "HIGH": 22.0,
                    "LOW": 18.0,
                    "CLOSE": 21.0,
                }
            )
            .to_csv(index=False)
            .encode()
        )
        return FetchedResponse(csv, url, 200, datetime.now(UTC))

    market = paths.data / "research/market"
    collect_market(
        universe,
        market,
        date(2014, 1, 1),
        date(2018, 12, 31),
        downloader=download,
        get=get,
        sleeper=lambda seconds: None,
    )
    return paths, protocol_path, universe, market


@pytest.fixture(scope="module")
def published(prepared):
    paths, protocol, universe, market = prepared
    manifest = runner.build_research_registry(paths, protocol, universe, market, workers=1)
    return (*prepared, manifest)


@pytest.fixture
def copied(published, tmp_path):
    paths, protocol, universe, market, manifest = published
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"
    shutil.copytree(paths.project_root, project)
    shutil.copytree(paths.workspace_root, workspace)
    result = ProjectPaths.resolve(project, workspace)
    return (
        result,
        project / protocol.relative_to(paths.project_root),
        workspace / universe.relative_to(paths.workspace_root),
        workspace / market.relative_to(paths.workspace_root),
        manifest,
    )


def artifact_directory(paths, manifest):
    return paths.artifacts / "research" / manifest["research_version"]


def test_real_causal_engines_publish_two_pairs_three_horizons_in_separate_db(published):
    paths, protocol, universe, market, manifest = published
    directory = artifact_directory(paths, manifest)
    assert manifest["stage"] == "registry"
    assert manifest["final_test_read"] is False
    assert manifest["protocol"]["final_test_locked"] is True
    assert {entry["pair_id"] for entry in manifest["pair_manifests"]} == {"KO__PEP", "HD__LOW"}
    assert len(manifest["files"]) == 12
    calendar = session_schedule(date(2014, 1, 1), date(2019, 4, 1))["trading_date"]
    session_number = {day: number for number, day in enumerate(calendar)}
    policies = set()
    for horizon in (10, 20, 30):
        events = pd.read_parquet(directory / f"h{horizon}_events.parquet")
        targets = pd.read_parquet(directory / f"h{horizon}_targets.parquet")
        assert not events.empty
        assert set(events.pair_id) == {"KO__PEP", "HD__LOW"}
        assert pd.to_datetime(events.event_date).dt.date.max() <= date(2018, 12, 31)
        assert not targets["outcome_type"].eq("LOCKED").any()
        joined = events[["event_id", "event_date"]].merge(
            targets, on="event_id", validate="one_to_one"
        )
        starts = pd.to_datetime(joined.event_date).dt.date.map(session_number)
        ends = pd.to_datetime(joined.horizon_end_date).dt.date.map(session_number)
        assert (ends - starts).eq(horizon).all()
        policies.update(targets["label_policy_version"].unique())
    assert len(policies) == 3
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT stage FROM analytics.research_versions").fetchall() == [
            ("registry",)
        ]
        assert connection.execute("SELECT status FROM ops.job_runs").fetchall() == [("SUCCESS",)]
        assert connection.execute("SELECT count(*) FROM analytics.model_versions").fetchone() == (
            0,
        )
        views = connection.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema='analytics' AND table_name LIKE 'research_registry_%'"
        ).fetchall()
        assert len(views) == 12
        for (name,) in views:
            assert connection.execute(f"SELECT count(*) FROM analytics.{name}").fetchone()[0] >= 0


def test_registered_replay_reuses_verified_outputs_without_estimating(published, monkeypatch):
    paths, protocol, universe, market, manifest = published

    def forbidden(*args, **kwargs):
        pytest.fail("An identical registered replay must not recompute relationships")

    monkeypatch.setattr(runner, "build_relationship_history", forbidden)
    assert runner.build_research_registry(paths, protocol, universe, market, workers=1) == manifest


@pytest.mark.parametrize("target", ["source_freeze", "pair_manifest", "pair_prices", "aggregate"])
def test_registered_replay_rejects_every_bound_source_and_cache(copied, target):
    paths, protocol, universe, market, manifest = copied
    directory = artifact_directory(paths, manifest)
    files = {
        "source_freeze": directory / "source_freeze.json",
        "pair_manifest": directory / "pairs/KO__PEP/manifest.json",
        "pair_prices": directory / "pairs/KO__PEP/h20_features.parquet",
        "aggregate": directory / "h20_events.parquet",
    }
    path = files[target]
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum|changed|freeze|cache"):
        runner.build_research_registry(paths, protocol, universe, market, workers=1)


def test_upstream_source_tampering_prevents_any_pair_computation(copied, monkeypatch):
    paths, protocol, universe, market, _ = copied
    raw = market / "raw/KO.parquet"
    raw.write_bytes(raw.read_bytes() + b"tampered")

    def forbidden(*args, **kwargs):
        pytest.fail("A source verification failure must precede pair computation")

    monkeypatch.setattr(runner, "_pair_dataset", forbidden)
    with pytest.raises(ValueError, match="checksum"):
        runner.build_research_registry(paths, protocol, universe, market, workers=1)


def test_interrupted_pair_batch_resumes_completed_hash_verified_pair(
    published, tmp_path, monkeypatch
):
    source_paths, protocol, universe, market, _ = published
    fresh = ProjectPaths.resolve(source_paths.project_root, tmp_path / "resumed")
    fresh_universe = fresh.data / "research/universe"
    fresh_market = fresh.data / "research/market"
    shutil.copytree(universe, fresh_universe)
    shutil.copytree(market, fresh_market)
    original = runner._pair_dataset
    completed = []

    def interrupted(arguments):
        if completed:
            raise RuntimeError("Fixture interruption before second pair")
        result = original(arguments)
        completed.append(result["pair_id"])
        return result

    monkeypatch.setattr(runner, "_pair_dataset", interrupted)
    with pytest.raises(RuntimeError, match="Fixture interruption"):
        runner.build_research_registry(fresh, protocol, fresh_universe, fresh_market, workers=1)
    assert completed == ["HD__LOW"]
    monkeypatch.setattr(runner, "_pair_dataset", original)
    estimates = []
    estimator = runner.build_relationship_history

    def counted(prices, pairs, *args, **kwargs):
        estimates.extend(pairs.pair_id.tolist())
        return estimator(prices, pairs, *args, **kwargs)

    monkeypatch.setattr(runner, "build_relationship_history", counted)
    manifest = runner.build_research_registry(
        fresh, protocol, fresh_universe, fresh_market, workers=1
    )
    assert estimates == ["KO__PEP"]
    assert len(manifest["pair_manifests"]) == 2
    with DuckDBConnectionFactory(fresh.database).connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM analytics.research_versions"
        ).fetchone() == (1,)


def test_changed_source_code_cannot_publish_under_original_computation(
    copied, tmp_path, monkeypatch
):
    paths, protocol, universe, market, manifest = copied
    fresh = ProjectPaths.resolve(paths.project_root, tmp_path / "fresh")
    fresh_universe = fresh.data / "research/universe"
    fresh_market = fresh.data / "research/market"
    shutil.copytree(universe, fresh_universe)
    shutil.copytree(market, fresh_market)
    original_cache = artifact_directory(paths, manifest) / "pairs"
    source = paths.project_root / "src/structural_break/research/protocol.py"

    def reuse_then_change(arguments):
        pair_id = arguments["pair"]["pair_id"]
        target = Path(arguments["cache_directory"]) / pair_id
        shutil.copytree(original_cache / pair_id, target)
        if pair_id == "HD__LOW":
            source.write_bytes(source.read_bytes() + b"\n# fixture mid-computation change\n")
        return json.loads((target / "manifest.json").read_bytes())

    monkeypatch.setattr(runner, "_pair_dataset", reuse_then_change)
    with pytest.raises(ValueError, match="Source code changed"):
        runner.build_research_registry(fresh, protocol, fresh_universe, fresh_market, workers=1)
    with DuckDBConnectionFactory(fresh.database).connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM analytics.research_versions"
        ).fetchone() == (0,)


def test_published_view_schema_agrees_with_frozen_parquet_files(published):
    paths, _, _, _, manifest = published
    suffix = manifest["research_version"].rsplit("_", 1)[-1]
    directory = artifact_directory(paths, manifest)
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        for item in manifest["files"]:
            view = f"research_registry_{item['name']}_{suffix}"
            stored = pd.read_parquet(directory / item["path"])
            result = connection.execute(f"SELECT * FROM analytics.{view}").fetchdf()
            assert list(result.columns) == list(stored.columns)
            assert len(result) == item["rows"]
            assert sha256_file(directory / item["path"]) == item["sha256"]


def test_failed_publication_resumes_verified_pair_caches_and_archives_manifest(
    published, tmp_path, monkeypatch
):
    paths, protocol, universe, market, completed = published
    fresh = ProjectPaths.resolve(paths.project_root, tmp_path / "publication_retry")
    fresh_universe, fresh_market = fresh.data / "research/universe", fresh.data / "research/market"
    shutil.copytree(universe, fresh_universe)
    shutil.copytree(market, fresh_market)
    pair_cache = artifact_directory(paths, completed) / "pairs"

    def cached(arguments):
        pair_id = arguments["pair"]["pair_id"]
        target = Path(arguments["cache_directory"]) / pair_id
        if not target.exists():
            shutil.copytree(pair_cache / pair_id, target)
        return json.loads((target / "manifest.json").read_bytes())

    original_finish = runner.RunRegistry.finish

    def fail_success(self, run_id, *, status, **kwargs):
        if status == "SUCCESS":
            raise RuntimeError("Fixture publication failure")
        return original_finish(self, run_id, status=status, **kwargs)

    monkeypatch.setattr(runner, "_pair_dataset", cached)
    monkeypatch.setattr(runner.RunRegistry, "finish", fail_success)
    with pytest.raises(RuntimeError, match="Fixture publication failure"):
        runner.build_research_registry(fresh, protocol, fresh_universe, fresh_market, workers=1)
    monkeypatch.setattr(runner.RunRegistry, "finish", original_finish)
    recovered = runner.build_research_registry(
        fresh, protocol, fresh_universe, fresh_market, workers=1
    )
    directory = artifact_directory(fresh, recovered)
    assert len(list(directory.glob("unregistered_manifest_*.json"))) == 1
    assert runner._registered_manifest(fresh, recovered["research_version"]) == recovered
    with DuckDBConnectionFactory(fresh.database).connect() as connection:
        assert connection.execute(
            "SELECT status FROM ops.job_runs ORDER BY started_at"
        ).fetchall() == [("FAILED",), ("SUCCESS",)]
        assert connection.execute(
            "SELECT count(*) FROM analytics.research_versions"
        ).fetchone() == (1,)


@pytest.fixture(scope="module")
def model_publication(published):
    from structural_break.intelligence.sentiment import FINBERT_MODEL, FINBERT_REVISION

    paths, _, universe, _, parent = published
    sec_directory = paths.workspace_root / "sec_metadata/source_v1"

    def get(url):
        match = re.search(r"CIK(\d{10})", url)
        if match:
            cik = match[1]
            rows = {
                "accessionNumber": [f"{cik}-{year % 100:02d}-000001" for year in range(2014, 2019)],
                "form": ["10-K"] * 5,
                "filingDate": [f"{year}-02-01" for year in range(2014, 2019)],
                "reportDate": [f"{year - 1}-12-31" for year in range(2014, 2019)],
                "acceptanceDateTime": [f"{year}-02-01T21:00:00Z" for year in range(2014, 2019)],
                "primaryDocument": ["report.htm"] * 5,
            }
            body = json.dumps({"cik": int(cik), "filings": {"recent": rows, "files": []}}).encode()
        elif url.endswith("index.json"):
            body = b'{"directory":{"item":[{"name":"report.htm","type":"file"}]}}'
        else:
            body = (
                b"<html><body>Quarterly earnings and revenue increased substantially.</body></html>"
            )
        return FetchedResponse(body, url, 200, datetime(2026, 10, 6, tzinfo=UTC))

    class Tone:
        model_name, model_revision = FINBERT_MODEL, FINBERT_REVISION

        def token_ids(self, text):
            return list(range(1, len(text.split()) + 1))

        def predict(self, windows):
            return [{"positive": 0.7, "negative": 0.1, "neutral": 0.2} for _ in windows]

    collect_sec_metadata(universe, sec_directory, get=get)
    events, _, _ = evidence_events(paths, parent["research_version"])
    directory = paths.workspace_root / "intelligence/fixture"
    build_event_intelligence(
        events,
        universe,
        sec_directory,
        directory,
        provider=None,
        sentiment_backend=Tone(),
        get=get,
        cache_workspace=paths.workspace_root / "cache",
        event_registry_id=parent["research_version"],
    )
    models = train_research_models(paths, parent["research_version"], directory, horizon=20)
    return paths, models, directory


def test_shared_source_proofs_preserve_all_predictions_reports_and_two_full_replays(
    model_publication, monkeypatch: pytest.MonkeyPatch
):
    from structural_break.research import intelligence
    from structural_break.research.source_proof import mint_source_proof

    paths, original, directory = model_publication
    original_verifier = intelligence.verify_event_intelligence
    replay_calls = []

    def tracked(*args, **kwargs):
        replay_calls.append("fresh full reconstruction")
        return original_verifier(*args, **kwargs)

    monkeypatch.setattr(intelligence, "verify_event_intelligence", tracked)
    registry = original["identity_inputs"]["registry_version"]
    first = mint_source_proof(paths, registry, directory, purpose="fitting_input")
    initial_path, initial_sha = Path(first["source_proof_path"]), first["source_proof_sha256"]
    model = train_research_models(
        paths,
        registry,
        directory,
        horizon=20,
        source_proof=initial_path,
        source_proof_sha256=initial_sha,
    )
    verify_research_models(
        paths, model["research_version"], source_proof=initial_path, source_proof_sha256=initial_sha
    )
    final = mint_source_proof(paths, registry, directory, purpose="independent_publication")
    verified = verify_research_models(
        paths,
        model["research_version"],
        source_proof=Path(final["source_proof_path"]),
        source_proof_sha256=final["source_proof_sha256"],
        publication=True,
    )
    assert len(replay_calls) == 2
    assert len(verified["native_max_errors"]) == 10
    assert max(verified["native_max_errors"].values()) <= 1e-12
    before, after = artifact_directory(paths, original), artifact_directory(paths, model)
    pd.testing.assert_frame_equal(
        pd.read_parquet(before / "predictions.parquet"),
        pd.read_parquet(after / "predictions.parquet"),
        check_exact=True,
    )
    assert json.loads((before / "report.json").read_bytes()) == json.loads(
        (after / "report.json").read_bytes()
    )


def test_complete_registry_evidence_model_flow_replays_all_ten_native_bundles(model_publication):
    paths, model, _ = model_publication
    replay = verify_research_models(paths, model["research_version"])
    assert len(replay["native_max_errors"]) == 10
    assert max(replay["native_max_errors"].values()) <= 1e-12
    assert replay["paired_comparison_reproduced"] is True
    assert replay["final_test_read"] is False
    directory = artifact_directory(paths, model)
    rows = pd.read_parquet(directory / "model_inputs.parquet")
    assert rows.event_type_UNKNOWN.eq(1).all()
    predictions = pd.read_parquet(directory / "predictions.parquet")
    assert set(predictions.event_id) <= set(rows.event_id)
    report = json.loads((directory / "report.json").read_bytes())
    assert report["cohorts"]["assessment"]["n"] > 0
    for family in report["models"].values():
        assert set(family) == {"A", "B_metadata", "B_tone", "B_catalyst", "B_both"}
        for variant in family.values():
            for scale in ("raw_assessment", "calibrated_assessment"):
                metrics = variant[scale]
                assert np.isfinite(metrics["log_loss"])
                assert np.isfinite(metrics["pair_balanced_log_loss"])
                assert np.isfinite(metrics["issuer_balanced_log_loss"])
    assert report["metric_policy"]["log_loss_probability_clip_epsilon"] == np.finfo(float).eps
    frozen_groups = set(report["assessment_slice_policy"]["business_group_universe"])
    for family in report["models"].values():
        for variant in family.values():
            for scale in ("raw", "calibrated"):
                slices = variant[f"{scale}_assessment_slices"]
                assert set(slices["business_group"]) == frozen_groups
                assert set(slices["ACTIVE"]) == {"False", "True"}
                assert (
                    sum(group["n"] for group in slices["ACTIVE"].values())
                    == (report["cohorts"]["assessment"]["n"])
                )


def test_model_verification_independently_reconstructs_log_loss(model_publication, monkeypatch):
    from structural_break.research import model_job

    paths, model, _ = model_publication
    original = model_job.research_metrics

    def changed_loss(rows, probabilities, threshold):
        metrics = original(rows, probabilities, threshold)
        metrics["log_loss"] += 0.1
        return metrics

    monkeypatch.setattr(model_job, "research_metrics", changed_loss)
    with pytest.raises(ValueError, match="assessment metrics do not reproduce"):
        verify_research_models(paths, model["research_version"])


def test_model_verification_independently_reconstructs_subgroup_coverage(
    model_publication, monkeypatch
):
    from structural_break.research import model_job

    paths, model, _ = model_publication
    original = model_job.assessment_slices

    def changed_slice(rows, probabilities, protocol, *, business_groups):
        slices = original(rows, probabilities, protocol, business_groups=business_groups)
        slices["ACTIVE"]["True"]["selected"] += 1
        return slices

    monkeypatch.setattr(model_job, "assessment_slices", changed_slice)
    with pytest.raises(ValueError, match="subgroup metrics do not reproduce"):
        verify_research_models(paths, model["research_version"])


def test_model_verification_rechecks_the_scientific_evidence_parent(model_publication, tmp_path):
    paths, model, intelligence = model_publication
    workspace = tmp_path / "workspace"
    shutil.copytree(paths.workspace_root, workspace)
    copied = ProjectPaths.resolve(paths.project_root, workspace)
    feature = workspace / intelligence.relative_to(paths.workspace_root) / "features.parquet"
    feature.write_bytes(feature.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_research_models(copied, model["research_version"])
