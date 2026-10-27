"""Colour roles and chart styling. A colour always means the same thing."""

from __future__ import annotations

from typing import Any

PAPER = "#171719"
PANEL = "#1D1E22"
INK = "#F2F3F5"
MUTED = "#ABB1BD"
GRID = "#373B43"
MODEL_A = "#DCE0E7"
MODEL_B = "#58A6FF"
ENTRY = "#D7B878"
ADVERSE = "#F08A92"
NEUTRAL = "#ABB1BD"
INACTIVE = "#292B30"

VARIANT_COLORS = {
    "A": MODEL_A,
    "B_metadata": "#A3CFFF",
    "B_tone": "#7EBBFF",
    "B_catalyst": "#DCE0E7",
    "B_both": MODEL_B,
}
RUNG_COLORS = {
    "BASELINE_0": "#9AA5B1",
    "BASELINE_1": NEUTRAL,
    "MODEL_A": MODEL_A,
    "MODEL_B": MODEL_B,
    "FULL_SYSTEM": "#C9CED6",
}
PARTITION_COLORS = {"fit": "#9AA5B1", "calibration": ENTRY, "assessment": MODEL_B}
FONT = "IBM Plex Sans, sans-serif"

CSS = f"""
<style>
.stApp {{ background: {PAPER}; color: {INK}; }}
.block-container {{ padding: 2rem 2.5rem 3rem; max-width: 1480px; }}
h1, h2, h3 {{ letter-spacing: -0.02em; text-wrap: balance; }}
h1 {{ font-size: 2rem !important; line-height: 1.18 !important; }}
h2 {{ font-size: 1.45rem !important; margin-top: 0.3rem; }}
h3 {{ font-size: 1.15rem !important; }}
p, li {{ line-height: 1.55; }}
a {{ text-underline-offset: 0.2em; }}
::selection {{ background: #285989; color: #fff; }}
* {{ scrollbar-color: #545C6A {PAPER}; scrollbar-width: thin; }}
input, textarea {{ caret-color: {MODEL_B}; }}
button:focus-visible, a:focus-visible, input:focus-visible {{
  outline: 2px solid {MODEL_B} !important; outline-offset: 3px;
}}
[data-testid="stSidebar"] {{ border-right: 1px solid {GRID}; }}
[data-testid="stSidebarNav"] a {{ border-radius: 2px; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
  border-left: 1px solid {MODEL_B}; color: {MODEL_B};
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a {{ border-radius:2px; }}
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {{
  border-left:1px solid {MODEL_B}; color:{MODEL_B};
}}
[data-testid="stCaptionContainer"] {{ color: {MUTED}; }}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
[data-testid="stMetricValue"] > div {{ font-size: 1.65rem; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; }}
.sb-lede {{ color: {MUTED}; font-size: 1rem; max-width: 72ch; margin: -0.3rem 0 1.2rem; }}
.sb-synthetic {{ background: {ADVERSE}; color: #fff; padding: 0.55rem 0.9rem;
  border-radius: 4px; font-weight: 600; margin-bottom: 1rem; }}
.sb-verdict {{ border-left: 1px solid var(--sb-accent); background: {PANEL};
  padding: 0.9rem 1.1rem; margin: 0.4rem 0 1rem; }}
.sb-verdict strong {{ display: block; font-size: 1.15rem; margin-bottom: 0.2rem; }}
.sb-chip {{ display: inline-block; padding: 0.08rem 0.5rem; border-radius: 999px;
  font-size: 0.82rem; border: 1px solid {GRID}; background: {PANEL}; margin-right: 0.3rem; }}
.sb-lock {{ color: {MUTED}; font-weight: 500; font-size: 0.87rem; }}
.sb-brand {{ font-size: 1.35rem; font-weight: 600; letter-spacing: -0.03em; }}
.sb-status {{ display:flex; flex-wrap:wrap; gap:0.4rem 1.2rem; color:{MUTED};
  font-size:0.85rem; padding-bottom:0.7rem; border-bottom:1px solid {GRID}; margin-bottom:1rem; }}
.sb-records {{ width:100%; border-collapse:collapse; font-size:0.9rem; }}
.sb-records th {{ color:{MUTED}; font-weight:400; text-align:left; padding:0.65rem; }}
.sb-records th, .sb-records td {{ border:0; }}
.sb-records td {{ padding:0.85rem 0.65rem; border-top:1px solid {GRID}; }}
.sb-records td.number {{ text-align:right; font-variant-numeric:tabular-nums; }}
.sb-records .selected {{ background:#1C2938; }}
.sb-records .selected td:first-child {{ border-left:1px solid {MODEL_B}; }}
.sb-records .role {{ display:block; font-size:0.8rem; color:{MUTED}; margin-top:0.25rem; }}
.sb-finding {{ max-width:68ch; font-size:1.04rem; line-height:1.6; }}
.sb-table-scroll {{ overflow-x:auto; }}
.sb-footer {{ margin-top:1.5rem; padding-top:0.8rem; border-top:1px solid {GRID};
  color:{MUTED}; font-size:0.82rem; }}
@media (prefers-reduced-motion: no-preference) {{
  button, a, .sb-records tr {{
    transition:background-color 160ms ease, color 160ms ease, border-color 160ms ease;
  }}
  [data-testid="stButton"] button:active {{ transform:translateY(1px); }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ scroll-behavior:auto !important; animation:none !important;
    transition:none !important; }}
}}
@media (max-width: 760px) {{
  .block-container {{ padding:1rem 1rem 2rem; }}
  h1 {{ font-size:1.65rem !important; }}
  .sb-records th, .sb-records td {{ padding:0.6rem 0.4rem; }}
}}
.sb-legend span {{ margin-right: 1.1rem; font-size: 0.86rem; color: {MUTED}; }}
.sb-legend i {{ display: inline-block; width: 18px; height: 3px; vertical-align: middle;
  margin-right: 0.35rem; }}
</style>
"""


def layout(**overrides: Any) -> dict[str, Any]:
    """Shared Plotly layout: quiet grid, tabular numbers, legend above the plot."""
    base: dict[str, Any] = {
        "font": {"family": FONT, "color": INK, "size": 13},
        "paper_bgcolor": PAPER,
        "plot_bgcolor": PAPER,
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
