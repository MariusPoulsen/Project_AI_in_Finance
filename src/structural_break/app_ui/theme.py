"""Colour roles and chart styling. A colour always means the same thing."""

from __future__ import annotations

from typing import Any

PAPER = "#F6F7F9"
PANEL = "#FFFFFF"
INK = "#172033"
MUTED = "#5F6B7A"
GRID = "#E3E7EC"
MODEL_A = "#5B6B82"
MODEL_B = "#0E7C6B"
ENTRY = "#C8A23A"
ADVERSE = "#B3261E"
NEUTRAL = "#3D5A80"
INACTIVE = "#E9DFC7"

VARIANT_COLORS = {
    "A": MODEL_A,
    "B_metadata": "#7FB7AE",
    "B_tone": "#4E9C8F",
    "B_catalyst": "#2C8A7A",
    "B_both": MODEL_B,
}
RUNG_COLORS = {
    "BASELINE_0": "#9AA5B1",
    "BASELINE_1": NEUTRAL,
    "MODEL_A": MODEL_A,
    "MODEL_B": MODEL_B,
    "FULL_SYSTEM": "#C9CED6",
}
FORECASTER_COLORS = {
    "model_a": MODEL_A,
    "r0": MODEL_B,
    "bag5": NEUTRAL,
    "track": ENTRY,
    "full_base": "#9AA5B1",
    "full": "#8E5EA2",
}
BOOK_COLORS = {"adopted": MODEL_B, "no_monitor": MODEL_A, "bag5": NEUTRAL, "full": ENTRY}
PERIOD_COLORS = {"2010–2017": "#9AA5B1", "2018–2023": NEUTRAL, "2024–2025": MODEL_B}
PARTITION_COLORS = {
    "fit": "#9AA5B1",
    "calibration": ENTRY,
    "assessment": MODEL_B,
    "Selection · 2010–2017": MODEL_A,
    "Holdout · 2018–2023": MODEL_B,
    "Final test · 2024–2025": ENTRY,
}
FONT = "IBM Plex Sans, sans-serif"

CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; max-width: 1320px; }}
@media (max-width: 600px) {{
  .st-key-investigation_actions [data-testid="stHorizontalBlock"] {{
    flex-wrap: nowrap; gap: 0.5rem;
  }}
  .st-key-investigation_actions [data-testid="stColumn"] {{
    flex: 0 1 auto !important; min-width: 0 !important; width: auto !important;
  }}
  .st-key-investigation_metrics [data-testid="stHorizontalBlock"] {{
    flex-wrap: wrap; gap: 1rem;
  }}
  .st-key-investigation_metrics [data-testid="stColumn"] {{
    flex: 1 1 calc(50% - 0.5rem) !important;
    min-width: 0 !important; width: calc(50% - 0.5rem) !important;
  }}
}}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; }}
.sb-lede {{ color: {MUTED}; font-size: 1.02rem; max-width: 70ch; margin: -0.4rem 0 1.2rem; }}
.sb-synthetic {{ background: {ADVERSE}; color: #fff; padding: 0.55rem 0.9rem;
  border-radius: 4px; font-weight: 600; margin-bottom: 1rem; }}
.sb-verdict {{ border-left: 4px solid var(--sb-accent); background: {PANEL};
  padding: 0.9rem 1.1rem; border-radius: 0 4px 4px 0; margin: 0.4rem 0 1rem; }}
.sb-verdict strong {{ display: block; font-size: 1.15rem; margin-bottom: 0.2rem; }}
.sb-chip {{ display: inline-block; padding: 0.08rem 0.5rem; border-radius: 999px;
  font-size: 0.82rem; border: 1px solid {GRID}; background: {PANEL}; margin-right: 0.3rem; }}
.sb-lock {{ color: {ADVERSE}; font-weight: 600; }}
.sb-final {{ color: {MODEL_B}; font-weight: 600; }}
.sb-legend span {{ margin-right: 1.1rem; font-size: 0.86rem; color: {MUTED}; }}
.sb-legend i {{ display: inline-block; width: 18px; height: 3px; vertical-align: middle;
  margin-right: 0.35rem; }}
</style>
"""


def layout(**overrides: Any) -> dict[str, Any]:
    """Shared Plotly layout: quiet grid, tabular numbers, legend above the plot."""
    base: dict[str, Any] = {
        "font": {"family": FONT, "color": INK, "size": 13},
        "paper_bgcolor": PANEL,
        "plot_bgcolor": PANEL,
        "margin": {"l": 56, "r": 18, "t": 36, "b": 44},
        "hoverlabel": {"font": {"family": FONT}},
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "bgcolor": "rgba(0,0,0,0)",
        },
        "xaxis": {"gridcolor": GRID, "zeroline": False, "linecolor": GRID},
        "yaxis": {"gridcolor": GRID, "zeroline": False, "linecolor": GRID},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base
