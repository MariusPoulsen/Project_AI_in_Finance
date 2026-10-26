"""Ingest FNSPID headlines for the universe and report event coverage (Decision 110, step 1).

No LLM calls and no outcomes: counts of company-specific headlines available in
the three sessions up to each signal close, for all h20 model events and for the
Decision 100 design candidates, by year.
"""
import json
from pathlib import Path

import pandas as pd

from structural_break.experiments import p6_agents as pa
from structural_break.experiments.p6_improvement import _sources
from structural_break.intelligence import headlines as hl

ws = Path("data/team")
out = Path("data/external/fnspid/headlines.parquet")
master = pd.read_parquet(ws / "universe/source_v1/security_master.parquet")
sources = [Path("data/external/fnspid") / name for name in ("All_external.csv", "nasdaq_exteral_data.csv")]
if all(s.exists() for s in sources):
    frame = hl.ingest(sources, master, out)
    base = "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/"
    hl.manifest(sources, {s.name: base + s.name for s in sources}, [out, out.with_name("articles.parquet")],
                out.with_name("manifest.json"))
else:
    frame = pd.read_parquet(out)  # compact store already built; raw files may be gone
print("by source:", frame.groupby("source").size().to_dict())
prices = pd.read_parquet(ws / "market/source_v1/prices.parquet", columns=["trading_date"])
sessions = pd.DatetimeIndex(sorted(pd.to_datetime(prices["trading_date"].unique())))
frame["session"] = hl.available_session(frame, sessions)
frame.to_parquet(out, index=False)
print(f"headlines: {len(frame):,} rows, {frame.specific.sum():,} company-specific, tickers {frame.ticker.nunique()} of {len(master)}")
print("specific headlines by year:", frame[frame.specific].groupby(frame.session.dt.year).size().to_dict())
print("date-only stamps:", round(float((~frame.same_day).mean()), 3))

version = _sources(ws).binding.evaluation.version
events = pd.read_parquet(ws / "artifacts/research" / version / "model_inputs.parquet", columns=["event_id", "pair_id", "event_date"])
pairs = pd.read_parquet(ws / "universe/source_v1/pair_universe.parquet", columns=["pair_id", "leg_a_security_id", "leg_b_security_id"])
events = events.merge(pairs, on="pair_id")
cov = hl.coverage(events, frame, sessions)
cov = cov.merge(events[["event_id", "event_date"]], on="event_id")
cov["year"] = pd.to_datetime(cov.event_date).dt.year
cov["any"] = (cov.headlines_a + cov.headlines_b) > 0
cov["both"] = (cov.headlines_a > 0) & (cov.headlines_b > 0)
candidates = set(pa.design_candidates(ws))
cov["candidate"] = cov.event_id.isin(candidates)
windows = pd.read_parquet("outputs/news_v1/windows.parquet")
eight_k = set(windows.loc[windows.leg_key.notna(), "event_id"])
cov["eight_k"] = cov.event_id.isin(eight_k)
cov["any_news"] = cov["any"] | cov["eight_k"]
cov.to_parquet("outputs/p6_desk/fnspid_coverage.parquet", index=False)
report = {
    "model_events": {"n": int(len(cov)), "any": float(cov["any"].mean()), "both": float(cov["both"].mean())},
    "candidates": {"n": int(cov.candidate.sum()), "any": float(cov.loc[cov.candidate, "any"].mean()), "both": float(cov.loc[cov.candidate, "both"].mean())},
    "candidates_by_year_any": cov[cov.candidate].groupby("year")["any"].mean().round(3).to_dict(),
    "candidates_any_news_incl_8k": float(cov.loc[cov.candidate, "any_news"].mean()),
    "candidates_by_year_any_news_incl_8k": cov[cov.candidate].groupby("year")["any_news"].mean().round(3).to_dict(),
    "model_events_any_news_incl_8k": float(cov["any_news"].mean()),
    "median_headlines_when_any": float((cov.headlines_a + cov.headlines_b)[cov["any"]].median()),
}
print(json.dumps(report, indent=1, default=str))
json.dump(report, open("outputs/p6_desk/fnspid_coverage.json", "w"), indent=1, default=str)
