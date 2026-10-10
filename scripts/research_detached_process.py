"""Service-launched Windows supervisor for one frozen intelligence command.

Win32_Process.Create starts this worker through WMI, independently of the
launching Codex shell. The worker owns its CLI child's log handles and waits for
its native exit; it does not poll research progress, retry, or launch models.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


def _write_json(path: Path, value: dict[str, Any], *, replace: bool = False) -> None:
    body = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(body)
    if replace:
        temporary.replace(path)
    else:
        if path.exists():
            raise FileExistsError(path)
        temporary.rename(path)


def _native_identity(handle: int | None = None) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("The service launcher requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.IsProcessInJob.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    ]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    native = kernel.GetCurrentProcess() if handle is None else handle
    creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(
        native,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        raise ctypes.WinError()
    in_job = wintypes.BOOL()
    if not kernel.IsProcessInJob(native, None, ctypes.byref(in_job)):
        raise ctypes.WinError()
    image = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(image))
    if not kernel.QueryFullProcessImageNameW(native, 0, image, ctypes.byref(size)):
        raise ctypes.WinError()
    return {
        "pid": int(kernel.GetProcessId(native)),
        "creation_filetime_utc": str((creation.dwHighDateTime << 32) | creation.dwLowDateTime),
        "executable": image.value,
        "is_process_in_job": bool(in_job.value),
    }


def _load_plan(path: Path, expected_sha256: str) -> dict[str, Any]:
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != expected_sha256:
        raise ValueError("Detached launch plan checksum changed")
    plan = json.loads(body)
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != "detached-intelligence-launch-v1"
    ):
        raise ValueError("Unsupported detached launch plan")
    arguments = plan.get("arguments")
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        raise ValueError("Launch arguments must be an explicit string array")
    if arguments[:4] != ["-u", "-m", "structural_break.research.cli", "build-intelligence"]:
        raise ValueError("Only the frozen intelligence command is permitted")
    if len(arguments[4:]) % 2:
        raise ValueError("Intelligence options must be explicit pairs")
    options = dict(zip(arguments[4::2], arguments[5::2], strict=True))
    expected = {
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
    source_prefetch = plan.get("source_prefetch", False)
    if type(source_prefetch) is not bool:
        raise ValueError("Source prefetch must be an explicit operational boolean")
    if source_prefetch:
        expected["--source-prefetch"] = "1"
    if options != expected or len(options) * 2 != len(arguments[4:]):
        raise ValueError("Detached command changes the frozen intelligence protocol")
    if plan["final_test_unlocked"] is not False or plan["max_events"] is not None:
        raise ValueError("Detached launch must retain full scope and the final lock")
    audit_body = Path(plan["resume_audit"]).read_bytes()
    if hashlib.sha256(audit_body).hexdigest() != plan["resume_audit_sha256"]:
        raise ValueError("Detached resume audit checksum changed")
    return cast(dict[str, Any], plan)


def run_worker(plan_path: Path, expected_sha256: str) -> int:
    if sys.platform != "win32":
        raise RuntimeError("The service launcher requires Windows")
    plan = _load_plan(plan_path, expected_sha256)
    worker = _native_identity()
    worker["parent_pid"] = os.getppid()
    worker["command_marker"] = Path(__file__).name
    state: dict[str, Any] = {
        "schema_version": "detached-intelligence-worker-v1",
        "plan_sha256": expected_sha256,
        "worker": worker,
        "status": "WAITING_FOR_LAUNCHER_ACKNOWLEDGEMENT",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "final_test_unlocked": False,
    }
    _write_json(Path(plan["worker_ready"]), state)
    exit_code = 1
    try:
        deadline = time.monotonic() + 25
        acknowledgement = Path(plan["worker_ack"])
        # A bounded startup handshake only; no ongoing progress-monitor loop.
        while not acknowledgement.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("Launcher did not acknowledge its service-parent proof")
            time.sleep(0.1)
        ack = json.loads(acknowledgement.read_bytes())
        if ack["plan_sha256"] != expected_sha256 or ack["wmi_wrapper_pid"] != os.getppid():
            raise ValueError("Launcher acknowledgement belongs to another process")
        with Path(plan["stdout"]).open("xb", buffering=0) as stdout:
            with Path(plan["stderr"]).open("xb", buffering=0) as stderr:
                child = subprocess.Popen(
                    [plan["executable"], *plan["arguments"]],
                    cwd=plan["project_root"],
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    close_fds=True,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                child_identity = _native_identity(int(cast(Any, child)._handle))
                child_identity["command_marker"] = "structural_break.research.cli"
                child_identity["parent_pid"] = os.getpid()
                state.update(
                    status="INTELLIGENCE_RUNNING",
                    child_process=child_identity,
                    observed_at_utc=datetime.now(UTC).isoformat(),
                )
                _write_json(Path(plan["worker_state"]), state, replace=True)
                # Native wait resides in this service-launched worker, not in Codex.
                exit_code = child.wait()
                state.update(status="INTELLIGENCE_EXITED", exit_code=exit_code)
    except Exception as error:
        state.update(status="WORKER_FAILED", error_type=type(error).__name__)
    finally:
        state["observed_at_utc"] = datetime.now(UTC).isoformat()
        state["exit_code"] = exit_code
        _write_json(Path(plan["worker_state"]), state, replace=True)
        _write_json(Path(plan["exit_receipt"]), state)
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args()
    raise SystemExit(run_worker(args.plan.resolve(), args.plan_sha256))


if __name__ == "__main__":
    main()
