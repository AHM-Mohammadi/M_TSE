"""One scheduled run: preserve new IDs, then archive prices for every known ID.

Run this via Windows Task Scheduler/cron after market close. Nothing is
scheduled automatically by installing this library.
"""
from datetime import datetime
from pathlib import Path
import sys

from M_TSE import M_TSE

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tse_data"
DATA.mkdir(parents=True, exist_ok=True)
tse = M_TSE(data_dir=DATA, min_interval=0.25, retries=3, market_source="auto")
try:
    print(datetime.now(), "Updating TDA identifiers...", flush=True)
    print(tse.update_tda(), flush=True)
except Exception as exc:
    print("CRITICAL: TDA refresh failed; existing archive remains intact:", exc,
          file=sys.stderr, flush=True)
    # Still try the price history of known identifiers from the previous TDA.


def progress(current, total, result):
    if current % 100 == 0 or current == total or result["status"] == "failed":
        print(datetime.now(), current, "/", total, result["id"], result["status"], flush=True)

report = tse.backfill(workers=3, min_hours=12, progress=progress)
report_path = DATA / f"sync_{datetime.now():%Y%m%d_%H%M%S}.csv"
report.to_csv(report_path, index=False, encoding="utf-8-sig")
tse.archive.backup(DATA / "latest_backup.sqlite")
print("Report:", report_path, flush=True)
print("Archive:", tse.archive.stats(), flush=True)
if not report.empty and "failed" in report["status"].values:
    raise SystemExit(2)
