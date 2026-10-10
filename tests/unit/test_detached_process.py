"""Detached worker input guards; no process launch, provider, or model access."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.research_detached_process import _load_plan


def _plan(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    audit = tmp_path / "audit.json"
    audit.write_text("{}", encoding="utf-8")
    plan: dict[str, Any] = {
        "schema_version": "detached-intelligence-launch-v1",
        "project_root": str(tmp_path),
        "workspace_root": str(tmp_path / "workspace"),
        "batch_name": "development_detached_v2",
        "resume_audit": str(audit),
        "resume_audit_sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
        "progress": str(tmp_path / "progress.json"),
        "final_test_unlocked": False,
        "max_events": None,
    }
    options = {
        "--project-root": plan["project_root"],
        "--workspace-root": plan["workspace_root"],
        "--registry-version": "research_registry_0bd415d2a5af1f4891dc1f0d",
        "--batch-name": plan["batch_name"],
        "--sec-source": "source_v3",
        "--sentiment-preprocessing": "sec-sentence-quality-wordpiece-v2",
        "--catalyst-max-events": "500",
        "--resume-audit": plan["resume_audit"],
        "--resume-audit-sha256": plan["resume_audit_sha256"],
        "--progress-file": plan["progress"],
    }
    plan["arguments"] = ["-u", "-m", "structural_break.research.cli", "build-intelligence"]
    for key, value in options.items():
        plan["arguments"].extend([key, value])
    return plan, tmp_path / "plan.json"


def _write(path: Path, plan: dict[str, Any]) -> str:
    path.write_text(json.dumps(plan), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_detached_worker_accepts_only_sha_bound_fixed_command(tmp_path: Path) -> None:
    plan, path = _plan(tmp_path)
    assert _load_plan(path, _write(path, plan)) == plan
    with pytest.raises(ValueError, match="plan checksum"):
        _load_plan(path, "0" * 64)


@pytest.mark.parametrize(
    ("option", "replacement"),
    [
        ("--registry-version", "other_registry"),
        ("--sec-source", "source_v2"),
        ("--sentiment-preprocessing", "exact-sentence-nonoverlap-wordpiece-v1"),
        ("--catalyst-max-events", "1000"),
    ],
)
def test_detached_worker_rejects_protocol_changes(
    tmp_path: Path, option: str, replacement: str
) -> None:
    plan, path = _plan(tmp_path)
    plan["arguments"][plan["arguments"].index(option) + 1] = replacement
    with pytest.raises(ValueError, match="frozen intelligence protocol"):
        _load_plan(path, _write(path, plan))


def test_detached_worker_rejects_partial_scope_or_duplicate_options(tmp_path: Path) -> None:
    plan, path = _plan(tmp_path)
    plan["arguments"].extend(["--max-events", "10"])
    with pytest.raises(ValueError, match="frozen intelligence protocol"):
        _load_plan(path, _write(path, plan))
    plan, path = _plan(tmp_path)
    plan["arguments"].extend(["--catalyst-max-events", "500"])
    with pytest.raises(ValueError, match="frozen intelligence protocol"):
        _load_plan(path, _write(path, plan))


def test_detached_worker_rejects_changed_audit_and_final_unlock(tmp_path: Path) -> None:
    plan, path = _plan(tmp_path)
    digest = _write(path, plan)
    Path(plan["resume_audit"]).write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="audit checksum"):
        _load_plan(path, digest)
    plan, path = _plan(tmp_path)
    plan["final_test_unlocked"] = True
    with pytest.raises(ValueError, match="final lock"):
        _load_plan(path, _write(path, plan))
