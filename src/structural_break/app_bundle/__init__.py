"""Read-only presentation bundles for the full research application (WS2 / PLAN P7).

A bundle holds compact, checksummed presentation tables derived from accepted
outputs: stored predictions, published reports, saved native models and verified
Phase 6 experiments. Building one never trains, downloads, calls a provider or
writes into the research workspace, and it never opens final-test data.
"""

from structural_break.app_bundle.contracts import (
    BUNDLE_SCHEMA_VERSION,
    HORIZONS,
    AppBundle,
    BundleIdentity,
    HorizonData,
    PairSeries,
)

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "HORIZONS",
    "AppBundle",
    "BundleIdentity",
    "HorizonData",
    "PairSeries",
]
