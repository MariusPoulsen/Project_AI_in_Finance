"""Decision 95: re-price every event under the adopted exit with per-stock costs."""
import pickle, pandas as pd, numpy as np
from pathlib import Path
from structural_break.backtest.production_policy import load_headline
from structural_break.experiments import p6_quant_trading as qt, p6_quant_costs as qc
h = load_headline(Path("configs")); cache = pickle.load(open("outputs/p6_quant/requests.pkl", "rb"))
prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
table = qc.lookup(qc.stock_inputs(prices))
rows = []
for e, (req, fr, m) in cache.items():
    row = {"event_id": e}
    st, net, _, _ = qt.exit_loop(req, fr, h, 1.0, 5.0, 20, m)
    row["flat_net"] = net if st == "COMPLETE" else np.nan
    for label, capital in (("1m", 1e6), ("10m", 1e7), ("100m", 1e8)):
        rate = qc.trade_rate_bps(table, req, fr, capital)
        row[f"rate_{label}"] = rate
        if rate is not None and st == "COMPLETE":
            st2, net2, _, _ = qt.exit_loop(req, fr, h, 1.0, 5.0, 20, m, cost_bps=rate)
            row[f"net_{label}"] = net2 if st2 == "COMPLETE" else np.nan
        else:
            row[f"net_{label}"] = np.nan
    rows.append(row)
out = pd.DataFrame(rows); out.to_parquet("outputs/p6_quant/cost_model_nets.parquet", index=False)
print(out[[c for c in out.columns if c.startswith("rate_")]].describe().round(2))
