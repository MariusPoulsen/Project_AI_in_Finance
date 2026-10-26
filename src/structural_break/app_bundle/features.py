"""Human-readable names and blocks for the frozen Model A / Model B predictors."""

from __future__ import annotations

from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.sentiment import SENTIMENT_FEATURE_COLUMNS
from structural_break.ml.features import FEATURE_FAMILIES
from structural_break.research.intelligence import METADATA_FEATURE_COLUMNS

TONE_COLUMNS = (*SENTIMENT_FEATURE_COLUMNS, "tone_aligned_contrast")

BLOCK_ORDER = (
    "Spread state",
    "Relationship quality",
    "Market context",
    "Security state",
    "Liquidity",
    "SEC metadata",
    "SEC tone (FinBERT)",
    "SEC catalyst (Gemma)",
    "Other",
)

_QUANT_BLOCKS = {
    "spread": "Spread state",
    "relationship": "Relationship quality",
    "market": "Market context",
    "security": "Security state",
    "liquidity": "Liquidity",
}

_LABELS = {
    "z_signed": "Signed spread z-score",
    "abs_z": "Absolute spread z-score",
    "divergence_sign": "Divergence direction",
    "adverse_z_velocity_1d": "Adverse z velocity (1d)",
    "adverse_z_velocity_5d": "Adverse z velocity (5d)",
    "spread_vol_20": "Spread volatility (20d)",
    "spread_vol_ratio_20_60": "Spread vol ratio 20d/60d",
    "days_since_equilibrium": "Days since spread equilibrium",
    "equilibrium_crossings_60": "Equilibrium crossings (60d)",
    "max_abs_z_20": "Max |z| (20d)",
    "coint_tstat": "Engle–Granger t-stat",
    "coint_pvalue": "Engle–Granger p-value",
    "coint_strength": "Cointegration strength",
    "half_life": "Mean-reversion half-life",
    "beta_abs": "Hedge ratio |β|",
    "beta_drift_pct": "Hedge-ratio drift (%)",
    "corr_20": "Return correlation (20d)",
    "corr_60": "Return correlation (60d)",
    "valid_months_last_6": "Valid months (last 6)",
    "market_return_1d": "Market return (1d)",
    "market_return_5d": "Market return (5d)",
    "sector_return_1d": "Sector return (1d)",
    "sector_return_5d": "Sector return (5d)",
    "vix_level": "VIX level (prev. session)",
    "vix_change_5d": "VIX change (5d)",
    "market_rv20": "Market realised vol (20d)",
    "aligned_relative_return_5d": "Aligned relative return (5d)",
    "aligned_relative_return_20d": "Aligned relative return (20d)",
    "abnormal_return_A_1d": "Leg A abnormal return (1d)",
    "abnormal_return_B_1d": "Leg B abnormal return (1d)",
    "volume_z_A_20": "Leg A volume z (20d)",
    "volume_z_B_20": "Leg B volume z (20d)",
    "relative_realised_vol_20": "Relative realised vol (20d)",
    "log_min_adv20": "Log min ADV (20d)",
    "adv_ratio": "ADV ratio A/B",
    "max_range_proxy20": "Max range proxy (20d)",
    "tone_aligned_contrast": "Tone contrast × divergence",
    "sec_recent_8k_count_asymmetry": "8-K count asymmetry",
    "sec_one_sided_recent_8k": "One-sided recent 8-K",
    "sentiment_net_contrast": "Net tone contrast A−B",
    "sentiment_net_asymmetry": "Net tone asymmetry",
    "sentiment_both_known": "Tone known for both legs",
    "sentiment_window_count": "Tone window count",
    "sentiment_chunk_count": "Tone chunk count",
    "one_sided_event": "One-sided catalyst",
    "source_count": "Catalyst source count",
    "document_recency_days": "Catalyst document age (days)",
    "extraction_confidence": "Extraction confidence",
    "evidence_available": "Catalyst evidence available",
}


_SEC_SUFFIXES = {
    "recent_8k_count_30d": "8-K filings in last 30 days",
    "days_since_latest_8k": "days since latest 8-K",
    "recent_items_2_02_earnings": "recent earnings 8-K (item 2.02)",
    "recent_items_5_02_management": "recent management change (item 5.02)",
    "periodic_recency_days": "days since latest 10-K/10-Q",
    "metadata_coverage_unknown": "SEC metadata UNKNOWN",
}


def feature_block(name: str) -> str:
    for family, columns in FEATURE_FAMILIES.items():
        if name in columns:
            return _QUANT_BLOCKS[family]
    if name in METADATA_FEATURE_COLUMNS:
        return "SEC metadata"
    if name in TONE_COLUMNS:
        return "SEC tone (FinBERT)"
    if name in EVENT_FEATURE_NAMES:
        return "SEC catalyst (Gemma)"
    return "Other"


def feature_label(name: str) -> str:
    if name in _LABELS:
        return _LABELS[name]
    for prefix, leg in (("sec_a_", "Leg A"), ("sec_b_", "Leg B")):
        if name.startswith(prefix):
            suffix = name.removeprefix(prefix)
            return f"{leg} {_SEC_SUFFIXES.get(suffix, 'SEC ' + suffix.replace('_', ' '))}"
    for prefix, leg in (("sentiment_a_", "Leg A"), ("sentiment_b_", "Leg B")):
        if name.startswith(prefix):
            return f"{leg} tone {name.removeprefix(prefix).replace('_', ' ')}"
    for group in (
        "event_type",
        "affected_leg",
        "materiality",
        "direction",
        "relationship_relevance",
    ):
        if name.startswith(group + "_"):
            value = name.removeprefix(group + "_").replace("_", " ").title()
            return f"Catalyst {group.replace('_', ' ')}: {value}"
    return name.replace("_", " ").capitalize()


def one_hot_value(row: dict[str, object], group: str, columns: tuple[str, ...]) -> str:
    """Return the active one-hot level, UNKNOWN when none is set (never 'no event')."""
    prefix = group + "_"
    for column in columns:
        if column.startswith(prefix):
            value = row.get(column)
            if isinstance(value, (int, float)) and value == 1:
                return column.removeprefix(prefix)
    return "UNKNOWN"
