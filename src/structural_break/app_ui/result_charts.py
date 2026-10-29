"""Charts for the headline results: forecaster curves and metrics, book values and returns."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from structural_break.app_ui import theme
from structural_break.app_ui.results import BOOKS, MODELS

FINAL_START = pd.Timestamp("2024-01-01")
HOLDOUT_START = pd.Timestamp("2018-01-01")


def _period_marks(figure: go.Figure, last: pd.Timestamp | None) -> None:
    figure.add_vline(x=HOLDOUT_START, line={"color": theme.MUTED, "dash": "dot", "width": 1})
    if last is not None and last >= FINAL_START:
        figure.add_vrect(
            x0=FINAL_START, x1=last, fillcolor=theme.MODEL_B, opacity=0.07, line_width=0
        )


def roc(curves: pd.DataFrame, period: str, models: Iterable[str]) -> go.Figure:
    figure = go.Figure()
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
    for model in models:
        rows = curves[(curves.model == model) & (curves.period == period) & (curves.kind == "roc")]
        if rows.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=rows.x,
                y=rows.y,
                mode="lines",
                name=MODELS[model],
                line={"color": theme.FORECASTER_COLORS[model], "width": 2},
                hovertemplate="FPR %{x:.2f}<br>TPR %{y:.2f}<extra></extra>",
            )
        )
    figure.update_layout(
        theme.layout(
            height=360,
            xaxis={"title": "False-positive rate", "range": [0, 1]},
            yaxis={"title": "True-positive rate", "range": [0, 1]},
        )
    )
    return figure


def calibration(curves: pd.DataFrame, period: str, models: Iterable[str]) -> go.Figure:
    rows_all = curves[(curves.period == period) & (curves.kind == "calibration")]
    top = float(max(rows_all.x.max(), rows_all.y.max(), 0.05)) * 1.1 if len(rows_all) else 1.0
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[0, top],
            y=[0, top],
            mode="lines",
            line={"color": theme.GRID, "dash": "dash"},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    for model in models:
        rows = rows_all[rows_all.model == model]
        if rows.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=rows.x,
                y=rows.y,
                mode="lines+markers",
                name=MODELS[model],
                line={"color": theme.FORECASTER_COLORS[model], "width": 2},
                customdata=rows.n,
                hovertemplate="Predicted %{x:.3f}<br>Observed %{y:.3f}<br>n %{customdata}"
                "<extra></extra>",
            )
        )
    figure.update_layout(
        theme.layout(
            height=360,
            xaxis={"title": "Mean predicted probability (deciles)", "range": [0, top]},
            yaxis={"title": "Observed reversion rate", "range": [0, top]},
        )
    )
    return figure


def metric_bars(metrics: pd.DataFrame, metric: str, title: str, models: list[str]) -> go.Figure:
    figure = go.Figure()
    for period, color in theme.PERIOD_COLORS.items():
        rows = (
            metrics[metrics.period.eq(period)]
            .set_index("model")
            .reindex(models)
            .dropna(subset=[metric])
        )
        if rows.empty:
            continue
        figure.add_trace(
            go.Bar(
                y=[models.index(m) for m in rows.index],
                x=rows[metric],
                customdata=[MODELS[m] for m in rows.index],
                name=period,
                orientation="h",
                marker_color=color,
                hovertemplate="%{customdata}<br>"
                + title
                + " %{x:.4f}<extra>"
                + period
                + "</extra>",
            )
        )
    selected = metrics.loc[metrics.model.isin(models)]
    values = selected[metric].dropna()
    low = float(values.min()) if len(values) else 0.0
    high = float(values.max()) if len(values) else 1.0
    pad = (high - low) * 0.25 or 0.01
    for index, model in enumerate(models):
        if not selected.loc[selected.model.eq(model), metric].notna().any():
            label = (
                "N/A · entry rule"
                if model in {"baseline0", "baseline1"} and metric in {"log_loss", "brier"}
                else "N/A · not exported"
            )
            figure.add_annotation(
                x=0.03,
                xref="paper",
                y=index,
                yref="y",
                text=label,
                showarrow=False,
                xanchor="left",
                font={"color": theme.MUTED, "size": 12},
            )
    figure.update_layout(
        theme.layout(
            height=max(300, 60 * len(models) + 90),
            barmode="group",
            xaxis={"title": title, "range": [low - pad, high + pad]},
            yaxis={
                "type": "linear",
                "tickmode": "array",
                "tickvals": list(range(len(models))),
                "ticktext": [MODELS[m] for m in models],
                "range": [len(models) - 0.5, -0.5],
            },
            margin={"l": 230},
        )
    )
    return figure


def yearly(table: pd.DataFrame, title: str) -> go.Figure:
    figure = go.Figure()
    for model in [c for c in table.columns if c != "year"]:
        figure.add_trace(
            go.Scatter(
                x=table.year,
                y=table[model],
                mode="lines+markers",
                name=MODELS[model],
                line={"color": theme.FORECASTER_COLORS[model], "width": 2},
            )
        )
    figure.add_vline(x=2017.5, line={"color": theme.MUTED, "dash": "dot", "width": 1})
    if table.year.max() >= 2024:
        figure.add_vline(x=2023.5, line={"color": theme.MODEL_B, "dash": "dot", "width": 1})
    figure.update_layout(theme.layout(height=320, yaxis={"title": title}, xaxis={"dtick": 1}))
    return figure


def book_values(daily: pd.DataFrame, keys: Iterable[str], height: int = 360) -> go.Figure:
    figure = go.Figure()
    for key in keys:
        if key not in daily:
            continue
        figure.add_trace(
            go.Scatter(
                x=daily.session_date,
                y=daily[key],
                name=BOOKS[key],
                line={"color": theme.BOOK_COLORS[key], "width": 1.8 if key == "adopted" else 1.3},
                hovertemplate="%{x|%d %b %Y}<br>%{y:.3f}<extra></extra>",
            )
        )
    _period_marks(figure, daily.session_date.max())
    figure.update_layout(theme.layout(height=height, yaxis={"title": "Value (start 1.0)"}))
    return figure


def drawdowns(daily: pd.DataFrame, keys: Iterable[str]) -> go.Figure:
    figure = go.Figure()
    for key in keys:
        if key not in daily:
            continue
        value = daily[key]
        figure.add_trace(
            go.Scatter(
                x=daily.session_date,
                y=value / value.cummax() - 1,
                name=BOOKS[key],
                line={"color": theme.BOOK_COLORS[key], "width": 1.3},
                hovertemplate="%{x|%d %b %Y}<br>%{y:.1%}<extra></extra>",
            )
        )
    _period_marks(figure, daily.session_date.max())
    figure.update_layout(theme.layout(height=240, yaxis={"title": "Drawdown", "tickformat": ".0%"}))
    return figure


def monthly_heatmap(daily: pd.DataFrame, key: str) -> go.Figure:
    value = daily.set_index("session_date")[key]
    monthly = value.resample("ME").last().pct_change()
    monthly.iloc[0] = value.resample("ME").last().iloc[0] / value.iloc[0] - 1
    index = pd.DatetimeIndex(monthly.index)
    grid = (
        pd.DataFrame({"year": index.year, "month": index.month, "r": monthly.to_numpy()})
        .pivot(index="year", columns="month", values="r")
        .reindex(columns=range(1, 13))
    )
    limit = float(np.nanmax(np.abs(grid.to_numpy()))) or 0.01
    figure = go.Figure(
        go.Heatmap(
            z=grid.to_numpy(),
            x=[pd.Timestamp(year=2000, month=int(m), day=1).strftime("%b") for m in grid.columns],
            y=[str(y) for y in grid.index],
            zmin=-limit,
            zmax=limit,
            colorscale=[[0, theme.ADVERSE], [0.5, "#FFFFFF"], [1, theme.MODEL_B]],
            hovertemplate="%{y} %{x}<br>%{z:.2%}<extra></extra>",
            colorbar={"tickformat": ".1%"},
        )
    )
    figure.update_layout(
        theme.layout(
            height=26 * len(grid) + 90,
            yaxis={"autorange": "reversed", "type": "category", "dtick": 1},
        )
    )
    return figure


def reason_bars(trades: pd.DataFrame) -> go.Figure:
    grouped = (
        trades.groupby("exit_reason")
        .agg(n=("event_id", "size"), mean=("gross_return", "mean"))
        .sort_values("n", ascending=False)
    )
    figure = go.Figure(
        go.Bar(
            x=grouped.index,
            y=grouped["mean"] * 1e4,
            customdata=grouped["n"],
            marker_color=[theme.MODEL_B if v >= 0 else theme.ADVERSE for v in grouped["mean"]],
            hovertemplate="%{x}<br>%{y:+.1f} bps mean, %{customdata} trades<extra></extra>",
        )
    )
    figure.update_layout(
        theme.layout(height=300, yaxis={"title": "Mean gross return per trade (bps)"})
    )
    return figure
