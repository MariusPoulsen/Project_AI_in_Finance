import pickle, pandas as pd, numpy as np
from pathlib import Path
from structural_break.backtest.production_policy import load_headline
from structural_break.experiments import p6_quant_trading as qt, p6_boosting as pb
h = load_headline(Path("configs")); cache = pickle.load(open("outputs/p6_quant/requests.pkl", "rb"))
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
sel = pd.read_parquet("outputs/p6_quant/select__hb.parquet")
d = sel.merge(frame[["event_id", "event_date", "sector"]], on="event_id")
d["event_date"] = pd.to_datetime(d.event_date)
# Resolution date and net of each selected trade under the adopted exit (known after its exit).
rows = []
for r in d[d.top20].itertuples():
    if r.event_id not in cache: continue
    req, fr, m = cache[r.event_id]
    st, net, hold, _ = qt.exit_loop(req, fr, h, 1.0, 5.0, 20, m)
    if st == "COMPLETE":
        rows.append((r.event_id, r.sector, pd.Timestamp(req.sessions[hold + 1].session_date), net))
hist = pd.DataFrame(rows, columns=["event_id", "sector", "resolved", "net"]).sort_values("resolved")
skip = []
for r in d[d.top20].itertuples():
    past = hist[(hist.sector == r.sector) & (hist.resolved < r.event_date) & (hist.resolved >= r.event_date - pd.Timedelta(days=3 * 365))]
    skip.append(len(past) >= 20 and past.net.mean() < 0)
d.loc[d.top20, "skip"] = skip
d["top20"] = d.top20 & ~d.skip.fillna(False).astype(bool)
d[["event_id", "year", "top20"]].to_parquet("outputs/p6_quant/select__ka.parquet", index=False)
print("skipped", int(np.sum(skip)), "of", len(skip)); print(d[d.skip.fillna(False).astype(bool)].groupby(["year", "sector"]).size().unstack(fill_value=0))
