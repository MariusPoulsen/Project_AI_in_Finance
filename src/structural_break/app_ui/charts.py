"""Plotly figure builders. Inputs are already-filtered service frames."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from structural_break.app_ui import theme


def spread_bands(
    state: pd.DataFrame,
    events: pd.DataFrame | None = None,
    *,
    entry: float = 2.0,
    success: float = 0.5,
    adverse: float = 3.0,
    height: int = 360,
    shade_inactive: bool = True,
    probabilities: tuple[tuple[str, str], ...] = (("p_A", "A"), ("p_B", "B")),
) -> go.Figure:
    """Frozen daily z-score with entry, convergence and adverse-stop bands."""
    rows = state.copy()
    rows["trading_date"] = pd.to_datetime(rows["trading_date"])
    figure = go.Figure()
    if shade_inactive and "pair_status" in rows and len(rows):
        inactive = rows["pair_status"].ne("ACTIVE").astype(int)
        changes = inactive.diff().fillna(inactive.iloc[0]).ne(0).cumsum()
        for _, block in rows.groupby(changes):
            if block["pair_status"].iloc[0] != "ACTIVE":
                figure.add_vrect(
                    x0=block["trading_date"].iloc[0],
                    x1=block["trading_date"].iloc[-1],
                    fillcolor=theme.INACTIVE,
                    opacity=0.35,
                    line_width=0,
                    layer="below",
                )
    for level, color, dash in (
        (adverse, theme.ADVERSE, "dot"),
        (entry, theme.ENTRY, "dash"),
        (success, theme.MODEL_B, "dot"),
    ):
        for sign in (1, -1):
            figure.add_hline(y=sign * level, line_color=color, line_dash=dash, line_width=1.2)
    figure.add_trace(
        go.Scatter(
            x=rows["trading_date"],
            y=rows["z_score"].clip(-6, 6),
            mode="lines",
            line={"color": theme.INK, "width": 1.1},
            name="Spread z-score",
            hovertemplate="%{x|%d %b %Y}<br>z = %{y:.2f}<extra></extra>",
        )
    )
    if events is not None and len(events):
        frame = events.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        z = rows.set_index("trading_date")["z_score"]
        frame["z"] = frame["date"].map(z).fillna(frame.get("z_signed", np.nan))
        for outcome, color, symbol in (
            ("Reverted", theme.MODEL_B, "circle"),
            ("Did not revert", theme.ADVERSE, "x"),
        ):
            part = frame.loc[frame["outcome"].eq(outcome)]
            if part.empty:
                continue
            figure.add_trace(
                go.Scatter(
                    x=part["date"],
                    y=part["z"].clip(-6, 6),
                    mode="markers",
                    marker={
                        "color": color,
                        "size": 8,
                        "symbol": symbol,
                        "line": {"width": 1, "color": "#fff"},
                    },
                    name=f"Event · {outcome.lower()}",
                    customdata=np.stack([part[column] for column, _ in probabilities], axis=1),
                    hovertemplate=(
                        "%{x|%d %b %Y}<br>z = %{y:.2f}<br>P(revert) "
                        + " · ".join(
                            f"{label} %{{customdata[{i}]:.2f}}"
                            for i, (_, label) in enumerate(probabilities)
                        )
                        + "<extra></extra>"
                    ),
                )
            )
    figure.update_layout(
        theme.layout(height=height, yaxis={"title": "z-score", "range": [-4.5, 4.5]})
    )
    return figure


def normalised_prices(prices: pd.DataFrame, leg_a: str, leg_b: str) -> go.Figure:
    figure = go.Figure()
    for ticker, color in ((leg_a, theme.NEUTRAL), (leg_b, theme.ENTRY)):
        part = prices.loc[prices["ticker"].eq(ticker)]
        figure.add_trace(
            go.Scatter(
                x=part["trading_date"],
                y=part["index"],
                name=ticker,
                line={"color": color, "width": 1.4},
                hovertemplate="%{x|%d %b %Y}<br>%{y:.1f}<extra>" + ticker + "</extra>",
            )
        )
    figure.update_layout(theme.layout(height=260, yaxis={"title": "Index (start = 100)"}))
    return figure


def beta_history(snapshots: pd.DataFrame) -> go.Figure:
    rows = snapshots.copy()
    rows["estimation_date"] = pd.to_datetime(rows["estimation_date"])
    colors = rows["pair_status"].map({"ACTIVE": theme.MODEL_B}).fillna(theme.MUTED)
    figure = go.Figure(
        go.Scatter(
            x=rows["estimation_date"],
            y=rows["beta"],
            mode="lines+markers",
            line={"color": theme.GRID, "width": 1},
            marker={"color": colors, "size": 6},
            customdata=rows["pair_status"],
            hovertemplate="%{x|%b %Y}<br>β = %{y:.3f}<br>%{customdata}<extra></extra>",
            showlegend=False,
        )
    )
    figure.update_layout(theme.layout(height=240, yaxis={"title": "Hedge ratio β"}))
    return figure


def waterfall(explanation: dict[str, Any], limit: int = 8) -> go.Figure:
    """Largest feature pushes on one event's log-odds, plus the remainder."""
    parts = explanation["contributions"].head(limit)
    other = explanation["margin"] - explanation["base"] - float(parts["contribution"].sum())
    labels = [*parts["label"].tolist(), "All other features"]
    values = [*parts["contribution"].astype(float).tolist(), other]
    colors = [theme.MODEL_B if v >= 0 else theme.ADVERSE for v in values[:-1]] + [theme.MUTED]
    figure = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker={"color": colors},
            text=[f"{v:+.2f}" for v in values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>%{x:+.3f} log-odds<extra></extra>",
        )
    )
    figure.add_vline(x=0, line_color=theme.INK, line_width=1)
    limit_x = max(abs(v) for v in values) * 1.35 if values else 1.0
    figure.update_layout(
        theme.layout(
            height=70 + 30 * len(labels),
            xaxis={
                "title": "Push on the log-odds of reverting (teal raises, red lowers)",
                "range": [-limit_x, limit_x],
            },
            yaxis={"autorange": "reversed"},
            margin={"l": 230, "t": 20},
            showlegend=False,
        )
    )
    return figure


def coverage_lines(rows: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    palette = [theme.MODEL_A, theme.NEUTRAL, theme.MODEL_B, theme.ADVERSE, theme.ENTRY]
    for index, (label, part) in enumerate(rows.groupby("label", sort=False)):
        part = part.sort_values("year")
        figure.add_trace(
            go.Scatter(
                x=part["year"],
                y=part["share"],
                name=str(label),
                mode="lines+markers",
                line={"color": palette[index % len(palette)], "width": 1.8},
                customdata=part["n"],
                hovertemplate="%{x}<br>%{y:.1%} of %{customdata} events<extra></extra>",
            )
        )
    figure.update_layout(
        theme.layout(
            height=340,
            yaxis={"title": "Share of events", "tickformat": ".0%", "range": [0, 1.02]},
            xaxis={"dtick": 2},
        )
    )
    return figure


def events_by_year(rows: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    for partition, part in rows.groupby("research_partition", sort=False):
        figure.add_trace(
            go.Bar(
                x=part["year"],
                y=part["events"],
                name=str(partition),
                marker_color=theme.PARTITION_COLORS.get(str(partition), theme.MUTED),
                customdata=part["reverted"],
                hovertemplate="%{x}<br>%{y} events<br>%{customdata:.1%} reverted<extra></extra>",
            )
        )
    figure.update_layout(
        theme.layout(
            height=300,
            barmode="stack",
            yaxis={"title": "Fresh divergence events"},
            xaxis={"dtick": 2},
        )
    )
    return figure


def drift(rows: pd.DataFrame, label: str) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=rows["year"],
            y=rows["p95"],
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=rows["year"],
            y=rows["p05"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(91,107,130,0.12)",
            line={"width": 0},
            name="5–95th percentile",
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=rows["year"],
            y=rows["p75"],
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=rows["year"],
            y=rows["p25"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(91,107,130,0.28)",
            line={"width": 0},
            name="Interquartile range",
            hoverinfo="skip",
        )
    )
    colors = rows["period"].map(theme.PARTITION_COLORS).fillna(theme.MUTED)
    figure.add_trace(
        go.Scatter(
            x=rows["year"],
            y=rows["p50"],
            mode="lines+markers",
            line={"color": theme.INK, "width": 1.6},
            marker={"color": colors, "size": 8},
            name="Median",
            customdata=np.stack([rows["n"], rows["missing_share"]], axis=1),
            hovertemplate="%{x}<br>median %{y:.3f}<br>n %{customdata[0]}, missing "
            "%{customdata[1]:.1%}<extra></extra>",
        )
    )
    figure.update_layout(theme.layout(height=320, yaxis={"title": label}, xaxis={"dtick": 2}))
    return figure
