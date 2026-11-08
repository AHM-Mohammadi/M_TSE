"""M_TSE: Tehran Stock Exchange (TSETMC) data + durable identifier / price archive.

    from M_TSE import M_TSE
    tse = M_TSE(data_dir="tse_data")
"""
from pathlib import Path

from .client import TSETMCClient
from .market import (Market, filter_type, parse_watch, parse_depth, parse_overview,
                     parse_market_watch, parse_market_watch_depth, parse_overview_new, TYPE_CODES)
from .derivatives import Derivatives
from .history import History, apply_adjustments, parse_history, parse_adjustments
from .archive import Archive
from .errors import TSEMarketError, DataSourceError, InstrumentNotFound, AmbiguousTicker
from .utils import normalize, ticker_key, coerce_id, to_excel, gregorian_to_jalali, jalali_to_gregorian

__version__ = "1.3.1"

import json as _json
import os as _os

CONFIG_FILE = Path(_os.environ.get("M_TSE_CONFIG", Path.home() / ".m_tse" / "config.json"))


def get_data_dir():
    """Archive folder saved by set_data_dir() or the first-run prompt (None if unset)."""
    try:
        value = _json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("data_dir")
        return Path(value) if value else None
    except (OSError, ValueError):
        return None


def set_data_dir(path):
    """Remember the archive folder for every later M_TSE() call without data_dir."""
    folder = Path(path).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(_json.dumps({"data_dir": str(folder)}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    return folder


def _ask_data_dir():
    default = Path.home() / "Documents" / "M_TSE_data"
    print("M_TSE: archive folder is not set yet / پوشه ذخیره آرشیو هنوز تعیین نشده است.")
    try:
        answer = input(f"Where should the archive be stored? / آرشیو کجا ذخیره شود؟\n[Enter = {default}]: ")
    except (EOFError, OSError):
        answer = ""
    answer = answer.strip().strip('"').strip("'")
    folder = set_data_dir(answer or default)
    print(f"M_TSE: archive folder saved / ذخیره شد: {folder}\n"
          f"(change later with: from M_TSE import set_data_dir; set_data_dir(r'...'))")
    return folder


class M_TSE:
    """Facade over the online market, derivatives, history and the local SQLite archive.

    Parameters
    ----------
    data_dir : folder for ``tse_archive.sqlite`` and ``Ticker Data Archive.xlsx``.
        If omitted: the folder saved with ``set_data_dir`` is used; on the very
        first run the user is asked where to store the archive.
    market_source : 'new' (cdn.tsetmc.com, default), 'old' (old.tsetmc.com) or
        'auto' (new, then old on failure).
    traded_only : library-wide default for days without trades. ``False``
        (default) keeps and stores every day; ``True`` drops them. Every
        method also accepts ``traded_only=`` to override this per call.
    """

    def __init__(self, data_dir=None, *, timeout=18, retries=3, min_interval=0.2,
                 market_source="new", traded_only=False, client=None, seed=True,
                 enrich=True):
        if data_dir is None:
            data_dir = get_data_dir() or _ask_data_dir()
        root = Path(data_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self.client = client or TSETMCClient(timeout=timeout, retries=retries,
                                             min_interval=min_interval, market_source=market_source)
        self.traded_only = bool(traded_only)
        self.archive = Archive(db_path=root / "tse_archive.sqlite",
                               tda_path=root / "Ticker Data Archive.xlsx", seed=seed)
        self.market = Market(self.client, registry=self.archive, enrich=enrich)
        self.derivatives = Derivatives(self.market)
        self.history = History(self.client, self.archive, traded_only=self.traded_only)
        self.data_dir = root

    def _traded(self, traded_only):
        return self.traded_only if traded_only is None else bool(traded_only)

    def update_tda(self):
        """Fetch the market watch and add/refresh IDs; old/expired IDs are kept."""
        return self.archive.update_tda(self.market, export=True)

    def backfill(self, *, ids=None, types=None, workers=3, min_hours=0,
                 refresh_adjustments=False, progress=None, traded_only=None):
        """Download and store daily prices of all (or the given) archived IDs."""
        return self.archive.sync_many(self.client, ids=ids, types=types, workers=workers,
                                      min_hours=min_hours, refresh_adjustments=refresh_adjustments,
                                      progress=progress, traded_only=self._traded(traded_only))

    def sync(self, instrument_id, *, refresh_adjustments=False, traded_only=None):
        return self.archive.sync_one(instrument_id, self.client,
                                     refresh_adjustments=refresh_adjustments,
                                     traded_only=self._traded(traded_only))

    def stored_history(self, instrument_id, *, adjusted=False, start=None, end=None,
                       traded_only=None):
        """Offline history from SQLite (uses the library-wide traded_only default)."""
        return self.archive.history(instrument_id, adjusted=adjusted, start=start, end=end,
                                    traded_only=self._traded(traded_only))


TSEMarketKit = M_TSE  # backward-compatible alias for code written for TSEMarketKit 1.0

__all__ = ["M_TSE", "TSEMarketKit", "TSETMCClient", "Market", "Derivatives", "History",
           "Archive", "filter_type", "parse_watch", "parse_depth", "parse_overview",
           "parse_market_watch", "parse_market_watch_depth", "parse_overview_new", "TYPE_CODES",
           "TSEMarketError", "DataSourceError", "InstrumentNotFound", "AmbiguousTicker",
           "apply_adjustments", "parse_history", "parse_adjustments",
           "normalize", "ticker_key", "coerce_id", "to_excel",
           "gregorian_to_jalali", "jalali_to_gregorian", "set_data_dir", "get_data_dir"]
