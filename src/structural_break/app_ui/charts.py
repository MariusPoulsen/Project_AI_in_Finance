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
                    customdata=np.stack([part["p_A"], part["p_B"]], axis=1),
                    hovertemplate=(
                        "%{x|%d %b %Y}<br>z = %{y:.2f}<br>P(revert) A %{customdata[0]:.2f}"
                        " · B %{customdata[1]:.2f}<extra></extra>"
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


def ladder(comparison: pd.DataFrame, family: str) -> go.Figure:
    """Assessment Brier loss for A and every B ablation (lower is better)."""
    rows = comparison.loc[comparison["family"].eq(family)]
    colors = [theme.VARIANT_COLORS.get(v, theme.MUTED) for v in rows["variant"]]
    figure = go.Figure(
        go.Bar(
            x=rows["brier"],
            y=rows["model"],
            orientation="h",
            marker={"color": colors},
            text=[f"{v:.4f}" for v in rows["brier"]],
            textposition="outside",
            customdata=np.stack([rows["n"], rows["positives"]], axis=1),
            hovertemplate="%{y}<br>Brier %{x:.4f}<br>n = %{customdata[0]}, positives = "
            "%{customdata[1]}<extra></extra>",
        )
    )
    low = float(rows["brier"].min()) if len(rows) else 0.0
    high = float(rows["brier"].max()) if len(rows) else 1.0
    pad = max((high - low) * 1.5, high * 0.02)
    figure.update_layout(
        theme.layout(
            height=280,
            xaxis={
                "title": "Assessment Brier loss (lower is better)",
                "range": [max(0, low - pad), high + pad],
            },
            yaxis={"autorange": "reversed"},
            margin={"l": 170},
        )
    )
    return figure


def delta_forest(comparison: pd.DataFrame, family: str) -> go.Figure:
    """B − A Brier difference with the paired quarter-block 95% interval."""
    rows = comparison.loc[comparison["family"].eq(family) & comparison["variant"].ne("A")]
    figure = go.Figure()
    figure.add_vline(x=0, line_color=theme.INK, line_width=1)
    for _, row in rows.iterrows():
        has_interval = row["ci_low"] is not None and not pd.isna(row["ci_low"])
        color = theme.VARIANT_COLORS.get(row["variant"], theme.MUTED)
        figure.add_trace(
            go.Scatter(
                x=[row["delta_brier_B_minus_A"]],
                y=[row["model"]],
                mode="markers",
                marker={"color": color, "size": 11},
                error_x=(
                    {
                        "type": "data",
                        "symmetric": False,
                        "array": [row["ci_high"] - row["delta_brier_B_minus_A"]],
                        "arrayminus": [row["delta_brier_B_minus_A"] - row["ci_low"]],
                        "color": color,
                        "thickness": 2,
                    }
                    if has_interval
                    else None
                ),
                showlegend=False,
                hovertemplate=(
                    f"{row['model']}<br>Δ Brier %{{x:.5f}}"
                    + (
                        f"<br>95% [{row['ci_low']:.5f}, {row['ci_high']:.5f}]"
                        if has_interval
                        else ""
                    )
                    + "<extra></extra>"
                ),
            )
        )
    figure.update_layout(
        theme.layout(
            height=240,
            xaxis={"title": "Δ Brier, B − A (negative favours B)", "zeroline": False},
            yaxis={"autorange": "reversed"},
            margin={"l": 170},
        )
    )
    return figure


def curve(rows: pd.DataFrame, kind: str, prevalence: float | None = None) -> go.Figure:
    figure = go.Figure()
    titles = {
        "roc": ("False-positive rate", "True-positive rate"),
        "pr": ("Recall", "Precision"),
        "reliability": ("Mean predicted probability", "Observed reversion rate"),
    }
    if kind == "roc":
        figure.add_trace(
            go.Scatter(
                x=[0, 1],
                y=[0, 1],
                mode="lines",
                line={"color": theme.GRID, "dash": "dash"},
                showlegend=False,
                hoverinfo="skip",
            )
        )
    if kind == "reliability" and len(rows):
        top = float(max(rows["x"].max(), rows["y"].max())) * 1.1
        figure.add_trace(
            go.Scatter(
                x=[0, top],
                y=[0, top],
                mode="lines",
                line={"color": theme.GRID, "dash": "dash"},
                name="Perfect calibration",
                hoverinfo="skip",
            )
        )
    if kind == "pr" and prevalence is not None:
        figure.add_hline(y=prevalence, line_color=theme.GRID, line_dash="dash")
    for variant, part in rows.groupby("variant", sort=False):
        color = theme.VARIANT_COLORS.get(str(variant), theme.MUTED)
        mode = "lines+markers" if kind == "reliability" else "lines"
        figure.add_trace(
            go.Scatter(
                x=part["x"],
                y=part["y"],
                mode=mode,
                name=str(part["model"].iloc[0]),
                line={"color": color, "width": 2.2 if variant in {"A", "B_both"} else 1.2},
                customdata=part["n"],
                hovertemplate="x %{x:.3f}<br>y %{y:.3f}<br>n %{customdata}<extra></extra>",
            )
        )
    x_title, y_title = titles[kind]
    figure.update_layout(
        theme.layout(
            height=320,
            showlegend=False,
            xaxis={"title": x_title},
            yaxis={"title": y_title},
            margin={"t": 16},
        )
    )
    return figure


def slice_bars(rows: pd.DataFrame) -> go.Figure:
    frame = rows.dropna(subset=["delta_brier_B_minus_A"]).copy()
    colors = np.where(frame["delta_brier_B_minus_A"] < 0, theme.MODEL_B, theme.MODEL_A)
    figure = go.Figure(
        go.Bar(
            x=frame["delta_brier_B_minus_A"],
            y=frame["group"],
            orientation="h",
            marker={"color": colors},
            customdata=np.stack([frame["n"], frame["positives"]], axis=1),
            hovertemplate="%{y}<br>Δ Brier %{x:.5f}<br>n = %{customdata[0]}, positives = "
            "%{customdata[1]}<extra></extra>",
        )
    )
    figure.add_vline(x=0, line_color=theme.INK, line_width=1)
    figure.update_layout(
        theme.layout(
            height=max(240, 26 * len(frame) + 80),
            xaxis={"title": "Δ Brier, B − A (descriptive, no interval)"},
            yaxis={"autorange": "reversed"},
            margin={"l": 200},
        )
    )
    return figure


def importance_bars(rows: pd.DataFrame, family: str) -> go.Figure:
    frame = rows.iloc[::-1]
    color = frame["block"].map(_block_color)
    figure = go.Figure(
        go.Bar(
            x=frame["mean_abs_contribution"],
            y=frame["label"],
            orientation="h",
            marker={"color": color},
            customdata=np.stack([frame["block"], frame["mean_contribution"]], axis=1),
            hovertemplate="%{y}<br>%{customdata[0]}<br>mean |contribution| %{x:.3f}<br>mean "
            "signed %{customdata[1]:.3f}<extra></extra>",
        )
    )
    unit = "log-odds" if family == "logistic" else "margin"
    figure.update_layout(
        theme.layout(
            height=max(300, 24 * len(frame) + 70),
            xaxis={"title": f"Mean |contribution| ({unit})"},
            margin={"l": 230},
        )
    )
    return figure


def _block_color(block: str) -> str:
    if block.startswith("SEC"):
        return {"SEC metadata": "#7FB7AE", "SEC tone (FinBERT)": "#4E9C8F"}.get(
            block, theme.MODEL_B
        )
    return theme.MODEL_A


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


def nav_chart(nav: pd.DataFrame, column: str, title: str, percent: bool = False) -> go.Figure:
    figure = go.Figure()
    for rung, part in nav.groupby("rung", sort=False):
        figure.add_trace(
            go.Scatter(
                x=part["date"],
                y=part[column],
                name=str(part["label"].iloc[0]),
                line={
                    "color": theme.RUNG_COLORS.get(str(rung), theme.MUTED),
                    "width": 1.8,
                    "shape": "hv",
                },
                hovertemplate="%{x|%d %b %Y}<br>%{y:.4f}<extra></extra>"
                if not percent
                else "%{x|%d %b %Y}<br>%{y:.2%}<extra></extra>",
            )
        )
    figure.update_layout(
        theme.layout(height=300, yaxis={"title": title, "tickformat": ".1%" if percent else None})
    )
    return figure


def cost_heatmap(rows: pd.DataFrame) -> go.Figure:
    table = rows.pivot_table(
        index="cost_bps_per_side",
        columns="annual_borrow_rate",
        values="mean_net_return",
        aggfunc="first",
    ).sort_index(ascending=False)
    values = table.to_numpy(dtype=float) * 1e4
    limit = float(np.nanmax(np.abs(values))) if np.isfinite(values).any() else 1.0
    figure = go.Figure(
        go.Heatmap(
            z=values,
            x=[f"{100 * c:g}% borrow" for c in table.columns],
            y=[f"{c:g} bps/side" for c in table.index],
            colorscale=[[0, theme.ADVERSE], [0.5, "#F2F3F5"], [1, theme.MODEL_B]],
            zmin=-limit,
            zmax=limit,
            text=[[("n/a" if np.isnan(v) else f"{v:+.1f}") for v in row] for row in values],
            texttemplate="%{text}",
            hovertemplate="%{y}, %{x}<br>mean net %{z:+.1f} bps<extra></extra>",
            colorbar={"title": "bps"},
        )
    )
    figure.update_layout(theme.layout(height=300, margin={"l": 100}))
    return figure


def forest(rows: pd.DataFrame) -> go.Figure:
    frame = rows.loc[rows["status"].eq("RUN")]
    figure = go.Figure()
    figure.add_vline(x=0, line_color=theme.INK, line_width=1)
    for _, row in frame.iterrows():
        estimate = row["estimate"]
        if estimate is None or pd.isna(estimate):
            continue
        interval = row["low"] is not None and not pd.isna(row["low"])
        figure.add_trace(
            go.Scatter(
                x=[estimate * 1e4],
                y=[row["comparison"]],
                mode="markers",
                marker={"color": theme.NEUTRAL, "size": 11},
                error_x=(
                    {
                        "type": "data",
                        "symmetric": False,
                        "array": [(row["high"] - estimate) * 1e4],
                        "arrayminus": [(estimate - row["low"]) * 1e4],
                        "color": theme.NEUTRAL,
                        "thickness": 2,
                    }
                    if interval
                    else None
                ),
                showlegend=False,
                hovertemplate="%{y}<br>%{x:+.2f} bps<extra></extra>",
            )
        )
    figure.update_layout(
        theme.layout(
            height=230,
            xaxis={"title": "Difference per raw candidate, right − left (bps)"},
            yaxis={"autorange": "reversed"},
            margin={"l": 170},
        )
    )
    return figure


def outcome_box(rows: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    for disposition, color in (
        ("Selected", theme.MODEL_B),
        ("Withheld (counterfactual)", theme.MUTED),
    ):
        part = rows.loc[rows["disposition"].eq(disposition)]
        figure.add_trace(
            go.Box(
                x=part["net_bps"],
                name=f"{disposition} (n={len(part)})",
                marker_color=color,
                boxmean=True,
                orientation="h",
            )
        )
    figure.add_vline(x=0, line_color=theme.INK, line_width=1)
    figure.update_layout(
        theme.layout(
            height=240,
            xaxis={"title": "Net return per priced trade (bps)"},
            showlegend=False,
            margin={"l": 190},
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


def timeline(periods: list[dict[str, Any]]) -> go.Figure:
    colors = ["#C9CED6", "#9AA5B1", theme.ENTRY, theme.MODEL_B, theme.ADVERSE]
    figure = go.Figure()
    for index, period in enumerate(periods):
        start, end = pd.Timestamp(period["start"]), pd.Timestamp(period["end"])
        figure.add_trace(
            go.Bar(
                x=[(end - start).days * 86_400_000],
                y=["Chronology"],
                base=[start],
                orientation="h",
                marker={
                    "color": colors[index % len(colors)],
                    "pattern": {"shape": "/" if period["period"] == "Final test" else ""},
                },
                name=period["period"],
                text=period["period"],
                textposition="inside",
                insidetextanchor="middle",
                hovertemplate=f"{period['period']}<br>{start:%b %Y} – "
                f"{end:%b %Y}<br>{period['use']}<extra></extra>",
            )
        )
    figure.update_layout(
        theme.layout(
            height=150,
            barmode="overlay",
            showlegend=False,
            xaxis={"type": "date"},
            yaxis={"visible": False},
            margin={"l": 10, "t": 10, "b": 30},
        )
    )
    return figure
