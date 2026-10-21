"""Decision 102: one netted book, pairs sleeve (P-7.5) + residual sleeve (prints 2010-2017 unless --holdout).

Usage: stage_r.py <stage-q targets, e.g. pca_continuous> [--speed 0.1] [--every 1] [--holdout]
"""
import sys, json, math, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_quant_portfolio as qp, p6_quant_costs as qc, p6_boosting as pb, p6_resid as pr
from structural_break.experiments.p6_improvement import _sources
choice = sys.argv[1]
holdout = "--holdout" in sys.argv
control = {"speed": float(sys.argv[sys.argv.index("--speed") + 1]) if "--speed" in sys.argv else 1.0, "every": int(sys.argv[sys.argv.index("--every") + 1]) if "--every" in sys.argv else 1}
out_dir = Path("outputs/p6_quant/stage_r"); out_dir.mkdir(parents=True, exist_ok=True)
blocks = (("2010-2017", 2010, 2017),) + ((("2018-2023", 2018, 2023), ("2010-2023", 2010, 2023)) if holdout else ())


def show(name, book):
    for label, a, b in blocks:
        v, c = pr.stats(book, a, b), pr.stats(book, a, b, cash=True)
        print(f"{name:18s} {label}: Sharpe {v['sharpe']:+.2f} CAGR {v['cagr']:+.2%} (+cash {c['cagr']:+.2%}) maxDD {v['maxdd']:.1%} vol {v['vol']:.1%} gross {v['gross']:.2f} cost {v['cost']:.2%}/yr", flush=True)


if holdout and (out_dir / "summary.json").exists():
    for name in json.load(open(out_dir / "summary.json")):
        show(name, pd.read_parquet(out_dir / f"book_{name}.parquet"))
    sys.exit()
capital = 1e7
# The Decision 100 pairs design, exactly as Stage P's P-7.5.
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
table = qc.lookup(qc.stock_inputs(prices))
design = qp.run_design(cache, chosen, (1.0, 5.0, 20, True), Path("configs"), 0.075, sectors, table, capital)
legs, units_gross = [], []
for event_id, fraction in design["allocations"].items():
    result = design["results"][event_id]
    if result.exit is None:
        continue
    request = cache[event_id][0]
    pa, pb_ = result.entry.price_a, result.entry.price_b
    units_gross.append(abs(result.position.units_a) * pa + abs(result.position.units_b) * pb_)
    for ticker, units, price in ((request.leg_a, result.position.units_a, pa), (request.leg_b, result.position.units_b, pb_)):
        legs.append(pr.Leg(str(ticker), pd.Timestamp(result.entry.session_date), pd.Timestamp(result.exit.session_date), fraction * units * price))
print(f"pairs trades {len(design['allocations'])}, legs {len(legs)}, gross per unit allocation median {np.median(units_gross):.4f}", flush=True)
panels = pr.load_panels(prices, sectors)
rf = pr.tbill(Path("data/external/irx_13w_tbill.csv"))
first, last = pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31")
# Engine check against the research portfolio's P-7.5 NAV.
ref = design["marks"]; ref = ref[ref.nav.notna()].copy()
ref_book = pd.DataFrame({"session_date": pd.to_datetime(ref.session_date), "daily_return": ref.daily_return.astype(float), "interest": 0.0, "turnover": 0.0, "cost": 0.0, "gross": ref.gross_fraction.astype(float), "names": 0})
ref_book = ref_book[ref_book.session_date.between(first, last)]
w = np.load(Path("outputs/p6_quant/stage_q") / f"targets_{choice}.npy")
books = {"pairs_engine": pr.run_book(panels, None, legs, first, last, capital, rf=rf)}
for lam in (0.25, 0.5, 1.0):
    books[f"net_l{lam}"] = pr.run_book(panels, w * lam, legs, first, last, capital, rf=rf, **control)
    books[f"sep_l{lam}"] = pr.run_book(panels, w * lam, legs, first, last, capital, net=False, rf=rf, **control)
check = {}
for label, a, b in (("2010-2017", 2010, 2017), ("2010-2023", 2010, 2023)):
    ref_years = ref_book.session_date.dt.year.between(a, b)
    rr = ref_book.daily_return[ref_years]
    check[label] = {"research_portfolio": float(rr.mean() / rr.std() * math.sqrt(252)), "engine": pr.stats(books["pairs_engine"], a, b)["sharpe"]}
print("engine check (Sharpe):", json.dumps(check), flush=True)
summary = {"check": check, "control": control}
for name, book in books.items():
    book.to_parquet(out_dir / f"book_{name}.parquet", index=False)
    summary[name] = {"2010-2017": pr.stats(book, 2010, 2017)}
    show(name, book)
json.dump(summary, open(out_dir / "summary_select.json", "w"), indent=1)
json.dump({k: v for k, v in summary.items() if k not in ("check", "control")}, open(out_dir / "summary.json", "w"), indent=1)
