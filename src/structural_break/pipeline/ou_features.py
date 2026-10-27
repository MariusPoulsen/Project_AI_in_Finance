"""Structural Ornstein-Uhlenbeck features for every event (DECISIONS 85).

Each pair's z-score is treated as a discrete OU (AR(1)) process,
z[t+1] = rho * z[t] + sigma * e, where:
- rho is the formation-window AR(1) coefficient of the spread (daily pair state);
- sigma is the realised standard deviation of daily z changes over the
  previous 60 sessions (point-in-time).

From the signal z, Monte Carlo paths (common random numbers, fixed seed) give:
- ``ou_p_label``: probability of the research label (|z| <= 0.5 before an
  adverse z >= 3 within 20 sessions);
- ``ou_p_tp``: probability of the adopted take profit (|z| <= 1.0 before an
  adverse z >= 5 within 20 sessions);
- ``ou_zgain``: expected z captured under that exit;
- ``ou_ev_bps``: expected net return per unit of gross exposure, i.e.
  ``ou_zgain * spread_std / (1 + |beta|)`` minus the frozen 10 bps round trip;
- ``ou_rho``, ``ou_sigma``: the inputs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from structural_break.pipeline import features as qf

PATHS = 2000
STEPS = 20
SEED = 5557
WINDOW = 60
ROUND_TRIP_BPS = 10.0
OU = ("ou_p_label", "ou_p_tp", "ou_zgain", "ou_ev_bps", "ou_rho", "ou_sigma")


def realised_sigma(workspace: Path) -> pd.DataFrame:
    folder = workspace / qf.REGISTRY / "pairs"
    parts = []
    for path in sorted(p for p in folder.iterdir() if p.is_dir()):
        state = pd.read_parquet(
            path / "daily_pair_state.parquet",
            columns=["pair_id", "trading_date", "z_velocity_1d", "ar1_rho"],
        )
        state = state.sort_values("trading_date")
        state["ou_sigma"] = state["z_velocity_1d"].rolling(WINDOW, min_periods=40).std()
        parts.append(state[["pair_id", "trading_date", "ou_sigma", "ar1_rho"]])
    out = pd.concat(parts, ignore_index=True)
    out["trading_date"] = pd.to_datetime(out["trading_date"])
    return out


def simulate(
    z0: np.ndarray, rho: np.ndarray, sigma: np.ndarray, shocks: np.ndarray
) -> dict[str, np.ndarray]:
    """Vectorised paths for a batch of events; sign-normalised so the divergence is positive."""

    x = np.abs(z0)[:, None] * np.ones((1, shocks.shape[0]))
    label_done = np.zeros_like(x, dtype=bool)
    label_win = np.zeros_like(x, dtype=bool)
    trade_done = np.zeros_like(x, dtype=bool)
    trade_win = np.zeros_like(x, dtype=bool)
    exit_x = np.full_like(x, np.nan)
    for step in range(STEPS):
        x = rho[:, None] * x + sigma[:, None] * shocks[:, step][None, :]
        # The research label: |z| <= 0.5 wins, adverse >= 3 loses.
        hit = ~label_done & (np.abs(x) <= 0.5)
        stop = ~label_done & (x >= 3.0)
        label_win |= hit
        label_done |= hit | stop
        # The adopted trading exit: |z| <= 1.0 take profit, adverse >= 5 disaster stop.
        take = ~trade_done & (np.abs(x) <= 1.0)
        bust = ~trade_done & (x >= 5.0)
        exit_x = np.where(take | bust, x, exit_x)
        trade_win |= take
        trade_done |= take | bust
    exit_x = np.where(np.isnan(exit_x), x, exit_x)
    gain = np.abs(z0)[:, None] - exit_x
    return {
        "ou_p_label": label_win.mean(axis=1),
        "ou_p_tp": trade_win.mean(axis=1),
        "ou_zgain": gain.mean(axis=1),
    }


def build(events: pd.DataFrame, workspace: Path) -> pd.DataFrame:
    sigma = realised_sigma(workspace).set_index(["pair_id", "trading_date"])
    key = pd.MultiIndex.from_arrays([events["pair_id"], pd.to_datetime(events["event_date"])])
    row = sigma.reindex(key)
    rho = np.clip(row["ar1_rho"].to_numpy(float), 0.0, 0.9999)
    sig = row["ou_sigma"].to_numpy(float)
    z0 = events["entry_z"].to_numpy(float)
    ok = np.isfinite(rho) & np.isfinite(sig) & np.isfinite(z0)
    rng = np.random.default_rng(SEED)
    shocks = rng.standard_normal((PATHS, STEPS))
    out = pd.DataFrame(index=events.index, columns=list(OU), dtype=float)
    index = np.flatnonzero(ok)
    for start in range(0, len(index), 1000):
        chunk = index[start : start + 1000]
        result = simulate(z0[chunk], rho[chunk], sig[chunk], shocks)
        for name, values in result.items():
            out.loc[out.index[chunk], name] = values
    out["ou_rho"] = rho
    out["ou_sigma"] = sig
    scale = events["spread_std"].astype(float) / (1 + events["beta"].astype(float).abs())
    out["ou_ev_bps"] = out["ou_zgain"] * scale.to_numpy() * 1e4 - ROUND_TRIP_BPS
    return pd.concat([events[["event_id"]], out], axis=1)
