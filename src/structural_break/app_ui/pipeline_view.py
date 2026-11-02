"""Compact vector flow diagram for the research pipeline."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from structural_break.app_ui import theme


def _stage(x: int, title: str, detail: str, subline: str, color: str) -> str:
    return f"""
    <g text-anchor="middle">
      <circle cx="{x}" cy="145" r="7" fill="{color}"/>
      <text x="{x}" y="190" font-size="20" font-weight="600"
            fill="{color}">{escape(title)}</text>
      <text x="{x}" y="217" font-size="15" fill="{theme.MUTED}">{escape(detail)}</text>
      <text x="{x}" y="240" font-size="15" fill="{theme.MUTED}">{escape(subline)}</text>
    </g>"""


def diagram(protocol: dict[str, Any], issuers: int) -> str:
    entry = float(protocol["entry_z"])
    horizon = int(protocol["primary_horizon"])
    stages = [
        (110, "Data", "Prices · filings · news", f"{issuers:,} issuers · VIX", theme.MODEL_A),
        (330, "Find divergences", "Relationships & features", f"Fresh |z| ≥ {entry:g}", theme.INK),
        (550, "Forecast", "R0 · bagged · +track", f"{horizon}-session probability", theme.MODEL_B),
        (770, "Build the book", "Select · size · manage", "Costs · risk · exits", theme.NEUTRAL),
        (990, "Evaluate", "Forecast quality", "Returns after costs", theme.INK),
    ]
    nodes = "".join(_stage(*stage) for stage in stages)
    links = "".join(
        f'<path d="M{start} 145H{end}" marker-end="url(#pipe-arrow)"/>'
        for start, end in ((126, 313), (346, 533), (566, 753), (786, 973))
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 270"
      role="img" aria-labelledby="pipe-title pipe-desc">
    <title id="pipe-title">Research pipeline, from data to forecasts and portfolio results</title>
    <desc id="pipe-desc">Data feeds divergence detection, reversion forecasts, the trading book
      and evaluation. Entry agents add evidence to the Full model. The position monitor
      contributes to exits.</desc>
    <defs>
      <marker id="pipe-arrow" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M1 1L9 5L1 9" fill="none" stroke="#9AA7B5" stroke-width="1.5"/>
      </marker>
      <marker id="pipe-agent-arrow" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="5" markerHeight="5" orient="auto">
        <path d="M1 1L9 5L1 9" fill="none" stroke="{theme.MODEL_B}" stroke-width="1.5"/>
      </marker>
      <marker id="pipe-monitor-arrow" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="5" markerHeight="5" orient="auto">
        <path d="M1 1L9 5L1 9" fill="none" stroke="{theme.NEUTRAL}" stroke-width="1.5"/>
      </marker>
    </defs>
    <rect x="1" y="1" width="1098" height="268" rx="12" fill="#FFFFFF"
          stroke="{theme.GRID}"/>
    <g fill="none" stroke="#9AA7B5" stroke-width="1.6">{links}</g>
    <g font-family="Arial, sans-serif">
      <rect x="460" y="14" width="180" height="62" rx="10" fill="#E3F2EF"/>
      <g text-anchor="middle" fill="{theme.MODEL_B}">
        <text x="550" y="39" font-size="17" font-weight="600">Entry agents</text>
        <text x="550" y="61" font-size="14">Adds scores to Full</text>
      </g>
      <path d="M550 77V132" stroke="{theme.MODEL_B}" stroke-width="1.6"
            marker-end="url(#pipe-agent-arrow)"/>
      <rect x="680" y="14" width="180" height="62" rx="10" fill="#EDF2F7"/>
      <g text-anchor="middle" fill="{theme.NEUTRAL}">
        <text x="770" y="39" font-size="17" font-weight="600">Position monitor</text>
        <text x="770" y="61" font-size="14">Assesses news for exits</text>
      </g>
      <path d="M770 77V132" stroke="{theme.NEUTRAL}" stroke-width="1.6"
            marker-end="url(#pipe-monitor-arrow)"/>
      {nodes}
    </g>
    </svg>"""


def render(protocol: dict[str, Any], issuers: int) -> None:
    st.image(diagram(protocol, issuers), width="stretch")
    st.caption(
        "Entry agents inform the Full model probability; the position monitor informs exits."
    )
