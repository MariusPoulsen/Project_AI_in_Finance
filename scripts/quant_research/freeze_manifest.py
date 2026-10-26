"""Decision 113: research freeze manifest for the final-test design (DRAFT until the owner signs off).

Pins the git commit, every adopted parameter and the SHA-256 of the code, configuration and
data inputs that define the Decision 110d book and the agent desk. It does not fetch
2024-2025 data, unlock anything or run the final test.
"""
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


# Every live package of the book, the forecasters, the agent desk and their inputs, plus scripts.
CODE = sorted(
    str(p).replace("\\", "/")
    for pattern in ("src/structural_break/pipeline/*.py", "src/structural_break/forecast/*.py",
                    "src/structural_break/book/*.py", "src/structural_break/agents/*.py",
                    "src/structural_break/decision/*.py", "src/structural_break/intelligence/*.py",
                    "src/structural_break/backtest/*.py", "scripts/**/*.py")
    for p in Path(".").glob(pattern)
)
DATA = [
    "outputs/p6_boosting2/scores.parquet",
    "outputs/p6_quant/scores__B+rule+ou__recent-bag5.parquet",
    "outputs/p6_quant/scores__B+rule+ou+track__recent-bag5.parquet",
    "outputs/p6_quant/r1_events.parquet",
    "outputs/p6_quant/features.parquet",
    "outputs/p6_quant/cost_model_nets.parquet",
    "outputs/p6_quant/stage_q/targets_pca_continuous.npy",
    "outputs/p6_quant/requests_long.pkl",
    "data/external/irx_13w_tbill.csv",
    "data/external/fnspid/manifest.json",
    "data/external/fnspid/headlines.parquet",
    "outputs/news_v1/windows.parquet",
    "outputs/p6_desk/entry_inventory.parquet",
    "outputs/p6_desk/monitor_inventory.parquet",
    "outputs/p6_desk/triage_runtime.json",
    "data/team/market/source_v1/prices.parquet",
    "data/team/universe/source_v1/pair_universe.parquet",
    "data/team/universe/source_v1/security_master.parquet",
]
CONFIGS = sorted(str(p).replace("\\", "/") for p in Path("configs").glob("*") if p.is_file())

design = {
    "selection": {
        "model": "R0: original Model B, fixed XGBoost (depth 3, 400 trees, lr 0.03, min_child_weight 20, "
                 "lambda 10, seed 42), Decision 45 walk-forward (train on labels ending before Y-1, "
                 "threshold from year Y-1 scores, score year Y)",
        "share": "top 20 % of each test year (cut = 80th percentile of the year Y-1 threshold-role scores)",
        "filters": ["skip R1 events", "skip spreads without a mean crossing for more than 120 sessions",
                    "skip the most expensive fifth of trades (per-stock cost model, year Y-1 cut)"],
        "dead_columns": "Model B's 28 v2 Gemma catalyst columns are inert for R0 (bit-identical predictions)",
    },
    "entry_and_execution": {
        "signal_and_entry": "signal at the session close; trades executed at the signal close (Decision 107)",
        "sizing": "7.5 % of NAV per entry, pairs gross entry cap 100 % (portfolio policy gross_entry_cap 1.0)",
        "costs": "per-stock costs at $10m: tiered half-spread 1/2/4/8 bps by ADV, square-root impact Y=0.7, "
                 "commission 0.5 bps, cap 200 bps; borrow 1 %/yr on shorts",
    },
    "exits": {
        "take_profit": "|z| <= 1.0",
        "stop_loss": "none on the z-score",
        "time_stop": "clip(ceil(1.5 x half-life), 10, 40) sessions; 20 when the half-life is unknown (Decision 112b)",
        "news_exit": "E3 adverse-tone 8-K news exit (Decisions 59-62)",
        "monitor_exit": "exit at the close of the first monitor check with adverse >= 5 and persistence >= 5 (Decision 110d)",
    },
    "residual_sleeve": "PCA (15 factors, 252-session window) residual s-score, continuous weights, lambda 0.25, "
                       "speed 0.10, trade band 0.15 % NAV (Decisions 104-105)",
    "risk": "constant-risk targeting at 4 % annual volatility on a 60-session window, scale clip [0.5, 2]; "
            "hard 200 % book gross cap (Decisions 106, 108)",
    "cash": "interest on NAV at the 13-week T-bill minus 0.25 %, floored at 0; Sharpe in excess of it",
    "agent_desk": {
        "graph": "pairs-desk-v3", "entry_prompts": "pairs-desk-prompts-v3.1", "monitor_prompt": "pairs-desk-monitor-v3.3",
        "models": {"analyst, advocates, facilitator, monitor": "gemma-4-26b-a4b-it",
                   "risk judge": "gemini-3.5-flash-lite"},
        "settings": "temperature 0, seed 42, minimal thinking, up to 2 corrections, sentence-ID citations, masked names",
        "triage": "pinned FinBERT (ProsusAI/finbert @ 4556d130, weights e15a7b57...); monitor called only if a headline is "
                  "toned against the position (net <= -0.2 long leg, >= +0.2 short leg)",
        "role_in_book": "only the monitor exit is used; entry agents are informational (Decision 110d)",
    },
}
protocol = {
    "test_years": [2024, 2025],
    "status": "LOCKED: nothing below may run, and no 2024-2025 data may be captured, before an owner-authored unlock "
              "record that cites this manifest's SHA-256",
    "data_to_capture_after_unlock": [
        "2024-2025 prices for the same 250-issuer roster (survivorship caveat stands)",
        "2024-2025 SEC filings (8-K etc.) through the existing pipeline",
        "a 2024-2025 company-headline source (FNSPID ends in 2023; see docs/NEWS_2024_2025.md)",
        "2024-2025 h20 events, relationship snapshots and features built by the frozen generation code",
    ],
    "model_refits": "walk-forward exactly as in selection: for test year Y the forecasters see only labels ending "
                    "before their scheme's cutoff; no parameter is re-tuned",
    "goal_1_report": "AUC-ROC, log loss and Brier on 2024-2025 h20 events: original Model B (R0) vs the pre-registered "
                     "B+rule+ou bag5 (verdict) and B+rule+ou+track bag5 (reported); agent features reported, not used",
    "goal_2_report": [
        "primary: the Decision 110d book (Sharpe in excess of cash, CAGR with and without cash, max drawdown, "
        "turnover, costs) for 2024-2025",
        "comparison: the same book without the monitor exit",
        "plan ladder: Baseline 0, Baseline 1, Model A, Model B and Full System under the frozen Decision 36 policy "
        "(existing backtest.freeze tooling), for comparability with the original plan",
    ],
    "no_retuning": "after viewing any 2024-2025 result, any change is a new, separately labelled experiment",
}
files = {p: sha(Path(p)) for p in CODE + DATA + CONFIGS if Path(p).exists()}
missing = [p for p in CODE + DATA + CONFIGS if not Path(p).exists()]
manifest = {
    "manifest_version": "p6-research-freeze-v1",
    "status": "DRAFT (owner review pending)",
    "created": datetime.now(UTC).isoformat(timespec="seconds"),
    "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "commit": git("rev-parse", "HEAD"),
            "clean": git("status", "--porcelain", "--untracked-files=no") == ""},
    "decisions": "Decisions 100-114 in docs/DECISIONS.md",
    "design": design,
    "final_test_protocol": protocol,
    "files_sha256": files,
    "missing_files": missing,
}
out = Path("outputs/freeze")
out.mkdir(parents=True, exist_ok=True)
raw = json.dumps(manifest, indent=1, sort_keys=True).encode()
(out / "research_freeze_manifest.json").write_bytes(raw)
print("manifest sha256", hashlib.sha256(raw).hexdigest(), "| files", len(files), "| missing", missing,
      "| git clean", manifest["git"]["clean"])
