"""Export every frozen development pair's history, without source replay or source writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from structural_break.app_bundle.workspace import CROSSING_COLUMNS, SNAPSHOT_COLUMNS
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.research.primary import checked_file, checked_json, registered_manifest


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=Path("demo/app_bundle"))
    parser.add_argument("--output", type=Path, default=Path("demo/pair_history"))
    args = parser.parse_args()
    workspace = args.workspace_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(workspace) or output.exists():
        raise ValueError("Choose a new presentation directory outside the source workspace")
    bundle = json.loads((args.bundle / "bundle.json").read_bytes())
    version = bundle["identity"]["registry_version"]
    registry_path, registry = registered_manifest(
        ProjectPaths.resolve(Path.cwd(), workspace), version, "registry"
    )
    protocol = registry["protocol"]
    if protocol != bundle["identity"]["protocol"]:
        raise ValueError("Pair history and the app input registry have different protocols")
    start, end = pd.Timestamp(protocol["fit_start"]), pd.Timestamp(protocol["development_end"])
    if end.year > 2023:
        raise ValueError("This history export is development-only")
    roster = pd.read_parquet(args.bundle / "pairs.parquet")
    known = set(roster.pair_id)
    records = {item["pair_id"]: item for item in registry["pair_manifests"]}
    if not known <= records.keys():
        raise ValueError("The app pair roster differs from the registered source")
    output.mkdir(parents=True)
    (output / "states").mkdir()
    writers: dict[str, Any] = {}
    files: dict[str, str] = {}
    pair_files: dict[str, str] = {}
    sources = {"registry_manifest": sha(registry_path)}

    def append(name: str, frame: pd.DataFrame) -> None:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if name not in writers:
            writers[name] = pq.ParquetWriter(output / name, table.schema, compression="zstd")
        writers[name].write_table(table)

    try:
        for index, pair_id in enumerate(sorted(known)):
            pair_path = confined_path(registry_path.parent, f"pairs/{pair_id}/manifest.json")
            pair = checked_json(pair_path, records[pair_id]["sha256"])
            sources[f"pair/{pair_id}"] = records[pair_id]["sha256"]
            source = checked_file(pair_path.parent, pair, "daily_pair_state")
            state = pd.read_parquet(
                source, columns=["trading_date", "z_score", "pair_status", "beta"]
            )
            state["trading_date"] = pd.to_datetime(state["trading_date"])
            if state["trading_date"].gt(end).any():
                raise ValueError("Final-test state rows in a development registry")
            state = state.loc[state["trading_date"].ge(start)].copy()
            if state.empty:
                raise ValueError(f"No history for registered pair {pair_id}")
            state.insert(0, "pair_id", pair_id)
            state["pair_status"] = state.pair_status.astype(str)
            name = f"states/{index % 8:02d}.parquet"
            pair_files[pair_id] = name
            append(name, state)
            for role, columns, target in (
                ("relationship_snapshots", SNAPSHOT_COLUMNS, "snapshots.parquet"),
                ("raw_crossings", CROSSING_COLUMNS, "crossings.parquet"),
            ):
                source = checked_file(pair_path.parent, pair, role)
                frame = pd.read_parquet(source)
                frame = frame[[c for c in columns if c in frame]].copy()
                if "status_reason" in frame:
                    frame["status_reason"] = frame.status_reason.map(
                        lambda v: (
                            ", ".join(map(str, v))
                            if isinstance(v, (list, tuple)) or hasattr(v, "tolist")
                            else str(v)
                        )
                    )
                if "pair_status" in frame:
                    frame["pair_status"] = frame.pair_status.astype(str)
                frame.insert(0, "pair_id", pair_id)
                append(target, frame)
            if (index + 1) % 100 == 0 or index + 1 == len(known):
                print(f"Verified and exported {index + 1}/{len(known)} pair histories", flush=True)
        market_item = next(item for item in registry["inputs"] if item["role"] == "market")
        market_path = confined_path(workspace, market_item["path"])
        market = checked_json(market_path, market_item["sha256"])
        price_path = market_path.parent / "prices.parquet"
        if sha(price_path) != market["files"]["prices.parquet"]:
            raise ValueError("Registered market prices failed their checksum")
        sources["market_manifest"] = market_item["sha256"]
        sources["prices"] = market["files"]["prices.parquet"]
        for batch in pq.ParquetFile(price_path).iter_batches(
            batch_size=65536, columns=["ticker", "trading_date", "adj_close"]
        ):
            frame = batch.to_pandas()
            frame.trading_date = pd.to_datetime(frame.trading_date)
            if frame.trading_date.gt(end).any():
                raise ValueError("Final-test prices in a development registry")
            frame = frame.loc[frame.trading_date.ge(start)].copy()
            if len(frame):
                frame["ticker"] = frame.ticker.astype(str)
                append("prices.parquet", frame)
    finally:
        for writer in writers.values():
            writer.close()
    files = {name: sha(output / name) for name in writers}
    manifest = {
        "schema_version": "pair-history-v1",
        "registry_version": version,
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "pairs": pair_files,
        "files": files,
        "source_hashes": sources,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    size_mb = sum((output / n).stat().st_size for n in files) / 1e6
    print(f"Exported {len(known)} pairs in {size_mb:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
