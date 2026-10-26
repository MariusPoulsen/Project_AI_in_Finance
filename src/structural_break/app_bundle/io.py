"""Write and read checksummed app bundles.

`write_bundle` only creates a new directory (never overwrites). `read_bundle`
re-verifies every file's SHA-256, the schema version and the final-test lock
before returning anything to the app.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.app_bundle.contracts import (
    BUNDLE_SCHEMA_VERSION,
    AppBundle,
    BundleIdentity,
    HorizonData,
)

MANIFEST = "bundle.json"
PAIR_TABLES = ("pairs", "pair_state", "pair_prices", "pair_snapshots", "pair_crossings")
HORIZON_TABLES = (
    "events",
    "curves",
    "importance",
    "contributions",
    "contribution_totals",
    "feature_profile",
    "strategy_nav",
    "strategy_trades",
)


class BundleError(ValueError):
    """A bundle is missing, malformed or fails verification."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(value, sort_keys=True, allow_nan=False, default=str, indent=1).encode()
    )
    return _digest(path)


def write_bundle(bundle: AppBundle, directory: Path) -> Path:
    if directory.exists():
        raise FileExistsError("Choose a new bundle directory; bundles are never overwritten")
    directory.mkdir(parents=True)
    files: list[dict[str, Any]] = []

    def frame(relative: str, value: pd.DataFrame) -> None:
        if value is None or not len(value.columns):
            files.append({"path": relative, "rows": 0, "sha256": None})
            return
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        value.reset_index(drop=True).to_parquet(path, index=False)
        files.append({"path": relative, "rows": len(value), "sha256": _digest(path)})

    def document(relative: str, value: Any) -> None:
        if value is None:
            files.append({"path": relative, "rows": 0, "sha256": None})
            return
        files.append(
            {"path": relative, "rows": 1, "sha256": _write_json(directory / relative, value)}
        )

    for name in PAIR_TABLES:
        frame(f"{name}.parquet", getattr(bundle, name))
    for horizon, data in bundle.horizons.items():
        document(f"h{horizon}/report.json", data.report)
        document(f"h{horizon}/strategy.json", data.strategy)
        for name in HORIZON_TABLES:
            frame(f"h{horizon}/{name}.parquet", getattr(data, name))
    identity = asdict(bundle.identity)
    identity["source"] = "synthetic" if bundle.identity.synthetic else "bundle"
    manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "identity": identity,
        "final_test_read": False,
        "files": files,
    }
    _write_json(directory / MANIFEST, manifest)
    return directory / MANIFEST


def read_bundle(directory: Path) -> AppBundle:
    path = directory / MANIFEST
    if not path.is_file():
        raise BundleError("No app bundle manifest at this location")
    manifest = json.loads(path.read_bytes())
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise BundleError("Unsupported app bundle schema")
    if manifest.get("final_test_read") is not False:
        raise BundleError("App bundles must keep the final test locked")
    entries = {item["path"]: item for item in manifest["files"]}
    root = directory.resolve()

    def checked(relative: str) -> Path | None:
        item = entries.get(relative)
        if item is None or item["sha256"] is None:
            return None
        file = (directory / relative).resolve()
        if root not in file.parents or not file.is_file():
            raise BundleError("App bundle file is missing or outside the bundle")
        if _digest(file) != item["sha256"]:
            raise BundleError(f"App bundle checksum differs: {relative}")
        return file

    def frame(relative: str) -> pd.DataFrame:
        file = checked(relative)
        return pd.read_parquet(file) if file is not None else pd.DataFrame()

    def document(relative: str) -> Any:
        file = checked(relative)
        return json.loads(file.read_bytes()) if file is not None else None

    raw = manifest["identity"]
    identity = BundleIdentity(
        schema_version=raw["schema_version"],
        source=raw["source"],
        synthetic=bool(raw["synthetic"]),
        primary_version=raw["primary_version"],
        registry_version=raw["registry_version"],
        intelligence_version=raw["intelligence_version"],
        evaluations={int(key): value for key, value in raw["evaluations"].items()},
        experiments={int(key): value for key, value in raw["experiments"].items()},
        protocol=raw["protocol"],
        showcase_pairs=tuple(raw["showcase_pairs"]),
        explanation_status=raw["explanation_status"],
        bundle_id=raw["bundle_id"],
    )
    end = pd.Timestamp(identity.protocol["development_end"]).date()
    horizons: dict[int, HorizonData] = {}
    for horizon in identity.evaluations:
        report = document(f"h{horizon}/report.json")
        if report is None or report.get("final_test_read") is not False:
            raise BundleError("Every published horizon needs its locked evaluation report")
        events = frame(f"h{horizon}/events.parquet")
        if len(events) and pd.to_datetime(events["event_date"]).dt.date.gt(end).any():
            raise BundleError("App bundle events must not include the final test")
        horizons[horizon] = HorizonData(
            report=report,
            events=events,
            curves=frame(f"h{horizon}/curves.parquet"),
            importance=frame(f"h{horizon}/importance.parquet"),
            contributions=frame(f"h{horizon}/contributions.parquet"),
            contribution_totals=frame(f"h{horizon}/contribution_totals.parquet"),
            feature_profile=frame(f"h{horizon}/feature_profile.parquet"),
            strategy=document(f"h{horizon}/strategy.json"),
            strategy_nav=frame(f"h{horizon}/strategy_nav.parquet"),
            strategy_trades=frame(f"h{horizon}/strategy_trades.parquet"),
        )
    tables = {name: frame(f"{name}.parquet") for name in PAIR_TABLES}
    return AppBundle(
        identity=identity,
        horizons=horizons,
        pairs=tables["pairs"],
        pair_state=tables["pair_state"],
        pair_prices=tables["pair_prices"],
        pair_snapshots=tables["pair_snapshots"],
        pair_crossings=tables["pair_crossings"],
    )
