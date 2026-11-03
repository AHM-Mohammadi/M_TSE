"""Controlled, injectable TSETMC HTTP adapter (no insecure SSL bypass).

Default data source is the *new* TSETMC API (cdn.tsetmc.com). The legacy
old.tsetmc.com market-watch is kept only as an optional fallback, because
TSETMC maintains the old site "as is" with no further development.
"""
from __future__ import annotations

import threading
import time
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import DataSourceError

API_BASE = "https://cdn.tsetmc.com/api"

# New market watch: every paper type, every instrument (traded or not),
# with five-level best limits (order book).
MARKET_WATCH_URL = (
    API_BASE + "/ClosingPrice/GetMarketWatch?market=0&industrialGroup="
    + "".join(f"&paperTypes%5B{i}%5D={i + 1}" for i in range(9))
    + "&showTraded=false&withBestLimits=true&hEven=0&RefID=0")
OVERVIEW_BASE = API_BASE + "/MarketData/GetMarketOverview"          # /1 TSE, /2 IFB
INSTRUMENT_INFO_BASE = API_BASE + "/Instrument/GetInstrumentInfo"   # /{insCode}
HISTORY_BASE = API_BASE + "/ClosingPrice/GetClosingPriceDailyList"  # /{insCode}/{n}
ADJUST_BASE = API_BASE + "/ClosingPrice/GetPriceAdjustList"         # /{insCode}

# Legacy (fallback only)
OLD_MARKET_URL = "https://old.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0"
MARKET_URL = OLD_MARKET_URL  # backward-compatible name

SOURCES = ("new", "old", "auto")

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 M_TSE/1.0"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tsetmc.com/",
    "Origin": "https://tsetmc.com",
}


class TSETMCClient:
    """HTTP client. ``market_source``: 'new' (default), 'old' or 'auto'.

    'auto' tries the new API and falls back to old.tsetmc.com on failure.
    """

    def __init__(self, *, timeout=18.0, retries=3, backoff=0.7,
                 min_interval=0.0, session_factory=None, market_source="new",
                 market_watch_url=MARKET_WATCH_URL, overview_base=OVERVIEW_BASE,
                 instrument_info_base=INSTRUMENT_INFO_BASE,
                 market_url=OLD_MARKET_URL, history_base=HISTORY_BASE,
                 adjust_base=ADJUST_BASE, headers=None):
        if market_source not in SOURCES:
            raise ValueError(f"market_source must be one of {SOURCES}")
        self.market_source = market_source
        self.market_watch_url = market_watch_url
        self.overview_base = overview_base.rstrip("/")
        self.instrument_info_base = instrument_info_base.rstrip("/")
        self.market_url = market_url
        self.history_base = history_base.rstrip("/")
        self.adjust_base = adjust_base.rstrip("/")
        self.timeout = float(timeout)
        self.min_interval = float(min_interval)
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self._session_factory = session_factory or Session
        self._thread_local = threading.local()
        self._lock = threading.Lock()
        self._last_request = 0.0
        # 403 is included: TSETMC intermittently answers 403 under load.
        self._retry = Retry(total=retries, connect=retries, read=retries, status=retries,
                            backoff_factor=backoff,
                            status_forcelist=[403, 429, 500, 502, 503, 504],
                            allowed_methods=["GET"], respect_retry_after_header=True,
                            raise_on_status=False)

    def _get_session(self):
        if not hasattr(self._thread_local, "session"):
            session = self._session_factory()
            session.headers.update(self.headers)
            session.mount("https://", HTTPAdapter(max_retries=self._retry))
            session.mount("http://", HTTPAdapter(max_retries=self._retry))
            self._thread_local.session = session
        return self._thread_local.session

    def _throttle(self):
        # Shared across all worker threads of this client instance.
        if self.min_interval > 0:
            with self._lock:
                remaining = self.min_interval - (time.monotonic() - self._last_request)
                if remaining > 0:
                    time.sleep(remaining)
                self._last_request = time.monotonic()

    def get(self, url: str, *, json=False):
        self._throttle()
        try:
            response = self._get_session().get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json() if json else response.text
        except Exception as exc:
            raise DataSourceError(f"TSETMC request failed: {url}: {exc}") from exc

    # ---------------- new API ----------------
    def market_watch(self) -> list[dict]:
        """Rows of the new market watch (list of dicts, with ``blDs`` depth)."""
        result = self.get(self.market_watch_url, json=True)
        if not isinstance(result, dict) or not isinstance(result.get("marketwatch"), list):
            raise DataSourceError("Malformed market-watch response (new API)")
        if not result["marketwatch"]:
            raise DataSourceError("Empty market-watch response (new API)")
        return result["marketwatch"]

    def market_overview(self, flow: int = 1) -> dict:
        """flow=1: Tehran Stock Exchange, flow=2: Iran Fara Bourse."""
        result = self.get(f"{self.overview_base}/{int(flow)}", json=True)
        if not isinstance(result, dict) or not isinstance(result.get("marketOverview"), dict):
            raise DataSourceError(f"Malformed market-overview response (flow={flow})")
        return result["marketOverview"]

    def instrument_info(self, instrument_id: str) -> dict:
        result = self.get(f"{self.instrument_info_base}/{instrument_id}", json=True)
        if not isinstance(result, dict) or not isinstance(result.get("instrumentInfo"), dict):
            raise DataSourceError(f"Malformed instrument-info response for {instrument_id}")
        return result["instrumentInfo"]

    def daily_prices(self, instrument_id: str, last=0):
        result = self.get(f"{self.history_base}/{instrument_id}/{int(last)}", json=True)
        if not isinstance(result, dict) or not isinstance(result.get("closingPriceDaily"), list):
            raise DataSourceError(f"Malformed historical response for {instrument_id}")
        return result["closingPriceDaily"]

    def price_adjustments(self, instrument_id: str):
        result = self.get(f"{self.adjust_base}/{instrument_id}", json=True)
        if not isinstance(result, dict) or not isinstance(result.get("priceAdjust"), list):
            raise DataSourceError(f"Malformed adjustment response for {instrument_id}")
        return result["priceAdjust"]

    # ---------------- legacy API ----------------
    def market_sections(self) -> list[str]:
        """Legacy old.tsetmc.com MarketWatchInit payload split by '@'."""
        response = self.get(self.market_url)
        sections = response.strip().split("@")
        if len(sections) < 4:
            raise DataSourceError(f"Unexpected market-watch payload: {len(sections)} sections")
        return sections
