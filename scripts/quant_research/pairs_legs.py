"""Stock legs of the Decision 100 pairs design (P-7.5), for open and close timing (Decisions 102, 107)."""
import pickle, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_quant_portfolio as qp, p6_quant_costs as qc, p6_boosting as pb, p6_resid as pr
from structural_break.experiments.p6_improvement import _sources
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
year = pd.to_datetime(frame.set_index("event_id").event_date).dt.year
s = pd.read_parquet("outputs/p6_boosting2/scores.parquet"); s = s[s.variant.eq("R0_xgb_fixed")]
r1 = set(pd.read_parquet("outputs/p6_quant/r1_events.parquet").event_id)
cross = pd.read_parquet("outputs/p6_quant/features.parquet").set_index("event_id")["state_days_since_zero_cross"]
costs = pd.read_parquet("outputs/p6_quant/cost_model_nets.parquet").set_index("event_id")
rt = 2 * costs["rate_10m"]; ry = year.reindex(rt.index)
cost_cut = {Y: np.nanquantile(rt[ry.eq(Y - 1)], 0.8) for Y in range(2010, 2024)}
chosen = []
for Y, g in s.groupby("year"):
    cut = float(np.quantile(g.loc[g.role.eq("threshold"), "score"], 0.8))
    chosen += list(g[g.role.eq("test") & (g.score >= cut)].event_id)
cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
chosen = [e for e in chosen if e not in r1 and not (cross.get(e, 0) > 120) and not (rt.get(e, np.inf) >= cost_cut.get(year.get(e), np.inf)) and e in cache]
sectors = _sources(Path("data/team")).security_sectors()
prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
design = qp.run_design(cache, chosen, (1.0, 5.0, 20, True), Path("configs"), 0.075, sectors, qc.lookup(qc.stock_inputs(prices)), 1e7)
legs = {"open": [], "close": []}
for event_id, fraction in design["allocations"].items():
    result = design["results"][event_id]
    if result.exit is None:
        continue
    request = cache[event_id][0]
    days = [x.session_date for x in request.sessions]
    trigger = days[days.index(result.exit.session_date) - 1]
    for ticker, units, price in ((request.leg_a, result.position.units_a, result.entry.price_a), (request.leg_b, result.position.units_b, result.entry.price_b)):
        f = fraction * units * price
        legs["open"].append(pr.Leg(str(ticker), pd.Timestamp(result.entry.session_date), pd.Timestamp(result.exit.session_date), f))
        legs["close"].append(pr.Leg(str(ticker), pd.Timestamp(days[0]), pd.Timestamp(trigger), f))
pickle.dump(legs, open("outputs/p6_quant/pairs_legs.pkl", "wb"))
print({k: len(v) for k, v in legs.items()})
