"""Export pre-final-test relationship diagnostics for the P2 manual acceptance check."""

import argparse
import json
from datetime import date
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.data.snapshots import json_bytes
from structural_break.services.relationships import RelationshipsRepository
from structural_break.storage.files import sha256_file, write_bytes
from structural_break.storage.relationships import json_value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--pairs", nargs="+", default=["KO__PEP", "HD__LOW", "TXN__ADI"])
    parser.add_argument("--end", type=date.fromisoformat, default=date(2023, 12, 31))
    args = parser.parse_args()
    if args.end >= date(2024, 1, 1):
        raise ValueError("P2 manual inspection is restricted to pre-final-test diagnostics")
    root = Path(__file__).resolve().parents[1]
    paths = ProjectPaths.resolve(root, args.workspace_root)
    repository = RelationshipsRepository(paths)
    manifest = repository.active_manifest()
    settings = manifest["config_snapshot"]["econometrics"]
    end = min(args.end, date.fromisoformat(manifest["end"]))
    start = date(max(2016, end.year - 2), 1, 1)
    fig, axes = plt.subplots(len(args.pairs), 2, figsize=(13, 3.3 * len(args.pairs)), squeeze=False)
    diagnostics = []
    for pair, row_axes in zip(args.pairs, axes, strict=True):
        daily = repository.pair_states(pair, start, end)
        if daily.empty:
            raise ValueError(f"No pre-final-test daily state for {pair}")
        with repository.factory.connect() as connection:
            monthly = connection.execute(
                """SELECT estimation_date,pair_status,alpha,beta,
                diagnostics->>'coint_pvalue' AS coint_pvalue,
                diagnostics->>'half_life_days' AS half_life_days,
                diagnostics->>'integration_flag' AS integration_flag
                FROM analytics.relationship_snapshots
                WHERE relationship_version=? AND pair_id=? AND estimation_date BETWEEN ? AND ?
                ORDER BY estimation_date""",
                [manifest["relationship_version"], pair, start, end],
            ).fetchdf()
        row_axes[0].plot(pd.to_datetime(daily["trading_date"]), daily["z_score"], lw=0.8)
        for boundary in (-settings["entry_z"], settings["entry_z"]):
            row_axes[0].axhline(boundary, color="#b35330", lw=0.8, ls="--")
        row_axes[0].set_title(f"{pair}: frozen monthly z-score")
        row_axes[0].set_ylabel("Formation standard deviations")
        row_axes[1].plot(
            pd.to_datetime(monthly["estimation_date"]),
            pd.to_numeric(monthly["coint_pvalue"]),
            marker=".",
            lw=0.8,
        )
        row_axes[1].axhline(settings["cointegration_alpha"], color="#b35330", lw=0.8, ls="--")
        row_axes[1].set_title("Engle–Granger / MacKinnon p-value")
        row_axes[1].set_ylim(-0.02, 1.02)
        for axis in row_axes:
            axis.grid(alpha=0.2)
        latest = monthly.iloc[-1].to_dict()
        diagnostics.append({"pair_id": pair, **json_value(latest)})
    fig.suptitle(
        f"P2 diagnostic inspection through {end}; no outcomes or trade results", fontsize=12
    )
    fig.tight_layout()
    destination = paths.artifacts / "reports" / manifest["relationship_version"]
    destination.mkdir(parents=True, exist_ok=True)
    image_path = destination / f"inspection_{end}.png"
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", dpi=160)
    plt.close(fig)
    write_bytes(image_path, image_buffer.getvalue())
    report = {
        "relationship_version": manifest["relationship_version"],
        "data_snapshot_id": manifest["data_snapshot_id"],
        "inspection_end": end.isoformat(),
        "image": image_path.relative_to(paths.workspace_root).as_posix(),
        "image_sha256": sha256_file(image_path),
        "latest_diagnostics": diagnostics,
    }
    write_bytes(destination / f"inspection_{end}.json", json_bytes(report))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
