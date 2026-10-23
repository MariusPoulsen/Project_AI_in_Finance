"""Decision 112c: FinBERT triage of position-monitor checks (local CPU, no API calls).

A check reaches the LLM monitor only if a headline that day is toned against the
position: net tone <= -0.2 on the long company or >= +0.2 on the short company.
Other checks are screened; they cannot trigger a monitor exit. Writes the
``triage`` column (and the tone fields) into the monitor inventory.
"""
import json
import re
from pathlib import Path

import pandas as pd

from structural_break.intelligence.recent_tone import TONE_POLICY
from structural_break.intelligence.sentiment import HuggingFaceFinBERT

OUT = Path("outputs/p6_desk")
THRESHOLD = 0.2
LINE = re.compile(r"^\d{4}-\d{2}-\d{2} headline: (.*?)(?:\. Summary: .*)?$")
inventory = pd.read_parquet(OUT / "monitor_inventory.parquet")
backend = HuggingFaceFinBERT(Path.home() / ".cache/huggingface/hub", TONE_POLICY, local_files_only=True)
checks, texts = [], {}
for row in inventory.itertuples(index=False):
    case = json.loads((OUT / "monitor_cases" / f"{row.file}.json").read_bytes())
    long_leg = None
    titles = {"A": [], "B": []}
    for chunk in case["event"]["evidence"]:
        if chunk["filing_id"] == "analyst-context":
            long_leg = re.search(r"long Company ([AB])", chunk["text"]).group(1)
            continue
        for line in chunk["text"].splitlines():
            match = LINE.match(line.strip())
            if match:
                titles[chunk["leg"]].append(match.group(1)[:400])
                texts[match.group(1)[:400]] = None
    checks.append((row.file, long_leg, titles))
unique = list(texts)
for start in range(0, len(unique), 256):
    batch = unique[start : start + 256]
    windows = [list(backend.token_ids(t))[: TONE_POLICY.max_tokens - 2] or [100] for t in batch]
    for text, p in zip(batch, backend.predict(windows), strict=True):
        texts[text] = p["positive"] - p["negative"]
    print(f"scored {min(start + 256, len(unique))}/{len(unique)} headlines", flush=True)
rows = []
for file, long_leg, titles in checks:
    short_leg = "B" if long_leg == "A" else "A"
    long_min = min((texts[t] for t in titles[long_leg]), default=0.0)
    short_max = max((texts[t] for t in titles[short_leg]), default=0.0)
    rows.append({"file": file, "long_min_net": long_min, "short_max_net": short_max,
                 "triage": bool(long_min <= -THRESHOLD or short_max >= THRESHOLD)})
tone = pd.DataFrame(rows)
inventory = inventory.drop(columns=[c for c in ("long_min_net", "short_max_net", "triage") if c in inventory])
inventory = inventory.merge(tone, on="file", how="left", validate="one_to_one")
inventory.to_parquet(OUT / "monitor_inventory.parquet", index=False)
print(json.dumps({"checks": len(inventory), "to_monitor": int(inventory.triage.sum()),
                  "share": round(float(inventory.triage.mean()), 3),
                  "trades_with_monitored_checks": int(inventory.loc[inventory.triage, "event_id"].nunique()),
                  "unique_headlines": len(unique)}))
