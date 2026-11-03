"""Sample: persist option OHLCV by immutable IDs before expiry."""
from datetime import datetime
from pathlib import Path
from M_TSE import M_TSE

DATA_DIR = Path("tse_data")
tse = M_TSE(data_dir=DATA_DIR, min_interval=0.3)
print("Updating identifier directory:", tse.update_tda())
ids = tse.archive.instruments(types=["CallOption", "PutOption"]).index.tolist()
print(f"Archiving {len(ids)} known option IDs (expired ones remain included)")


def progress(current, total, info):
    if current % 50 == 0 or current == total or info["status"] == "failed":
        print(f"{current}/{total}: {info['id']} {info['status']}")

report = tse.backfill(ids=ids, workers=3, min_hours=14, progress=progress)
out = DATA_DIR / f"options_sync_{datetime.now():%Y%m%d_%H%M}.csv"
report.to_csv(out, index=False, encoding="utf-8-sig")
print("Report:", out)
print("Stored price rows:", tse.archive.count_prices())
