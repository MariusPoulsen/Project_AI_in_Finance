"""Rebuild the app bundle with only what the pages still read.

The bundle was exported when the frozen A/B study compared the 10-, 20- and 30-session
horizons, with its strategy ladder and model diagnostics. The app now uses the 20-session
horizon only, and from it the events (scanner, pair detail), the per-event explanations
(pair detail) and the report's feature list (methodology). This reads the verified bundle and
writes a new one with just those parts and the A and B_both model entries; the values kept
are unchanged. Usage:

    python scripts/slim_app_bundle.py demo/app_bundle NEW_DIRECTORY
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from structural_break.app_bundle.contracts import BUNDLE_SCHEMA_VERSION, HorizonData
from structural_break.app_bundle.io import read_bundle, write_bundle
from structural_break.app_bundle.workspace import bundle_digest

KEEP_VARIANTS = ("A", "B_both")


def main() -> None:
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    bundle = read_bundle(source)
    horizon = int(bundle.identity.protocol["primary_horizon"])
    data = bundle.horizons[horizon]
    report = dict(data.report)
    report["models"] = {
        family: {key: value for key, value in variants.items() if key in KEEP_VARIANTS}
        for family, variants in report["models"].items()
    }
    empty = pd.DataFrame()
    slim = HorizonData(
        report=report,
        events=data.events,
        curves=empty,
        importance=empty,
        contributions=data.contributions,
        contribution_totals=data.contribution_totals,
        feature_profile=empty,
        strategy=None,
        strategy_nav=empty,
        strategy_trades=empty,
    )
    identity = bundle.identity
    evaluations = {horizon: identity.evaluations[horizon]}
    experiments = {h: v for h, v in identity.experiments.items() if h == horizon}
    payload = {
        "schema": BUNDLE_SCHEMA_VERSION,
        "primary": identity.primary_version,
        "evaluations": evaluations,
        "experiments": experiments,
        "showcase": list(identity.showcase_pairs),
        "slimmed_from": identity.bundle_id,
    }
    identity = replace(
        identity,
        evaluations=evaluations,
        experiments=experiments,
        bundle_id=bundle_digest(payload),
    )
    write_bundle(replace(bundle, identity=identity, horizons={horizon: slim}), target)
    read_bundle(target)  # verify what was written
    print(f"wrote {target}: horizon {horizon}, bundle {identity.bundle_id}")


if __name__ == "__main__":
    main()
