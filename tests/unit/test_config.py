import copy
import re
import shutil

import pytest
import yaml
from pydantic import ValidationError

from structural_break.config.loader import config_hash, load_config, normalized_config
from structural_break.config.models import ProjectConfig, RuntimeSettings


def test_universe_matches_canonical_document(project_root, config):
    decisions = (project_root / "docs/DECISIONS.md").read_text(encoding="utf-8")
    expected = re.findall(r"\| \d+ \| ([A-Z]+) \| ([A-Z]+) \|", decisions)
    assert len(expected) == 28
    assert [(p.leg_a, p.leg_b) for p in config.universe.pairs] == expected
    assert config.universe.pairs[0].pair_id == "KO__PEP"


def test_hash_stable_for_yaml_order_and_comments(project_root, tmp_path, config):
    shutil.copytree(project_root / "configs", tmp_path / "configs")
    data = config.data.model_dump(mode="json")
    (tmp_path / "configs/data.yaml").write_text(
        "# harmless comment\n" + yaml.safe_dump(dict(reversed(list(data.items())))),
        encoding="utf-8",
    )
    assert config_hash(load_config(tmp_path / "configs")) == config_hash(config)
    changed = config.model_dump(mode="json")
    changed["ml"]["seed"] += 1
    assert config_hash(ProjectConfig.model_validate(changed)) != config_hash(config)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("ml", "embargo_days", 1),
        ("ml", "final_test_locked", False),
        ("ml", "seed", "42"),
        ("econometrics", "entry_z", 0.1),
        ("econometrics", "cointegration_alpha", 2),
        ("econometrics", "entry_z", float("nan")),
        ("agents", "historical_web_browsing", True),
        ("data", "start", "2020-01-01"),
        ("decision", "status", "frozen"),
        ("backtest", "status", "frozen"),
        ("app", "read_only", False),
        ("app", "row_limt", 10),
    ],
)
def test_invalid_config_fails_before_work(config, section, field, value):
    raw = config.model_dump(mode="json")
    raw[section][field] = value
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("missing_alias", ["provider", "model"])
def test_live_agent_config_requires_each_alias(config, missing_alias):
    raw = config.model_dump(mode="json")
    raw["agents"]["mode"] = "live"
    raw["agents"][missing_alias] = None
    with pytest.raises(ValidationError, match="provider and model aliases"):
        ProjectConfig.model_validate(raw)


def test_live_agent_config_accepts_declared_aliases(config):
    raw = config.model_dump(mode="json")
    raw["agents"]["mode"] = "live"
    assert ProjectConfig.model_validate(raw).agents.mode == "live"


def test_overlapping_partitions_rejected(config):
    raw = config.model_dump(mode="json")
    raw["ml"]["validation"]["start"] = "2021-01-01"
    with pytest.raises(ValidationError, match="disjoint"):
        ProjectConfig.model_validate(raw)


def test_reversed_pair_rejected(config):
    raw = config.model_dump(mode="json")
    pair = copy.deepcopy(raw["universe"]["pairs"][0])
    pair["leg_a"], pair["leg_b"] = pair["leg_b"], pair["leg_a"]
    raw["universe"]["pairs"].append(pair)
    with pytest.raises(ValidationError, match="reversed"):
        ProjectConfig.model_validate(raw)


def test_missing_and_duplicate_yaml_rejected(project_root, tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path)
    shutil.copytree(project_root / "configs", tmp_path / "configs")
    path = tmp_path / "configs/data.yaml"
    path.write_text(path.read_text() + "\nversion: duplicate\n")
    with pytest.raises(ValueError, match="Duplicate YAML"):
        load_config(tmp_path / "configs")


def test_secrets_do_not_enter_research_config(config, monkeypatch, tmp_path):
    monkeypatch.setenv("SB_LLM_API_KEY", "fake-test-secret")
    dotenv = tmp_path / ".env"
    dotenv.write_text("SB_LLM_API_KEY=lower-precedence\n", encoding="utf-8")
    runtime = RuntimeSettings(_env_file=dotenv)
    assert runtime.llm_api_key.get_secret_value() == "fake-test-secret"
    assert "fake-test-secret" not in repr(runtime)
    assert "fake-test-secret" not in normalized_config(config)
    assert "llm_api_key" not in normalized_config(config)


def test_relative_storage_root_does_not_depend_on_cwd(project_root, tmp_path, monkeypatch):
    from structural_break.config.paths import ProjectPaths

    monkeypatch.chdir(tmp_path)
    paths = ProjectPaths.resolve(project_root, "generated")
    assert paths.workspace_root == project_root / "generated"
    assert paths.database == project_root / "generated/data/analytics/structural_break.duckdb"


@pytest.mark.parametrize("path", ["../outside", "/outside", "C:/outside", "a\\..\\b", "."])
def test_paths_cannot_escape_workspace(paths, path):
    with pytest.raises(ValueError):
        paths.data_path(path)


def test_symlink_escape_rejected(paths, tmp_path):
    paths.data.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    try:
        (paths.data / "link").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink creation privileges")
    with pytest.raises(ValueError):
        paths.data_path("link/file.txt")


def test_all_canonical_directories_created(paths):
    paths.create_directories()
    paths.create_directories()
    for relative in [
        "reference",
        "raw/sec/filings",
        "raw/yahoo/actions",
        "curated/market",
        "curated/evidence",
        "analytics",
        "snapshots",
        "cache/agent_runs",
        "demo",
    ]:
        assert paths.data_path(relative).is_dir()
    assert (paths.artifacts / "mlflow").is_dir()
    assert not paths.database.exists()
