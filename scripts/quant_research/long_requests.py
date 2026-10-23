"""Decision 111: 41-session trade paths for the time-stop test, from the frozen session builder and PriceBook.

Every rebuilt path must reproduce the cached 22-session path exactly (sessions and
adjusted prices), or the script stops. Sessions after the development end are never
built, so the locked final-test years are not read.
"""
import pickle
from datetime import date
from pathlib import Path

import pandas as pd

from structural_break.backtest import historical
from structural_break.backtest.historical import PriceBook
from structural_break.experiments import p6_quant_portfolio as qp
from structural_break.experiments.p6_improvement import _sources, _spec

HORIZON = 41  # monitored closes; 40-session time stop plus one spare close
ws = Path("data/team")
sources = _sources(ws)
spec = _spec(sources, date(2006, 1, 1), date(2023, 12, 31))
end = sources.binding.development_end
book = PriceBook.build(sources.prices(date(2005, 11, 1), end), spec)
cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
wanted = set(pd.read_parquet("outputs/p6_desk/entry_inventory.parquet").event_id)
long_cache, mismatches = {}, 0
for event_id in wanted:
    request, frozen, moments = cache[event_id]
    path = historical._sessions(request.sessions[0].session_date, HORIZON, end)
    bars = book.pair_bars(request.leg_a, request.leg_b, path)
    n = len(request.sessions)
    if tuple(path[:n]) != tuple(request.sessions) or tuple(bars[:n]) != tuple(request.prices):
        mismatches += 1
        continue
    long_cache[event_id] = (request.model_copy(update={"sessions": path, "prices": bars}), frozen, moments)
print(f"rebuilt {len(long_cache)} of {len(wanted)} paths; mismatches {mismatches}")
if mismatches:
    raise SystemExit("Rebuilt paths differ from the cached ones; not writing")
with open("outputs/p6_quant/requests_long.pkl", "wb") as handle:
    pickle.dump(long_cache, handle, protocol=pickle.HIGHEST_PROTOCOL)
