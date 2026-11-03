"""Edit DATA_DIR and run: python examples/quickstart.py. Requires TSETMC access."""
from pathlib import Path
from M_TSE import M_TSE

DATA_DIR = Path("tse_data")
tse = M_TSE(data_dir=DATA_DIR)
print("Local archive:", tse.archive.stats())
print("Market snapshot:")
print(tse.market.snapshot().head())
print("Call option snapshot:")
print(tse.derivatives.calls().head())
print("Adding new IDs to TDA:", tse.update_tda())
