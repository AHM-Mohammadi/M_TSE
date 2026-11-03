"""Raw/adjusted TSETMC daily histories. Adjustments never alter volume/value.

Columns: Date, JDate, Open, High, Low, Close (=pClosing, قیمت پایانی),
Last (=pDrCotVal, آخرین معامله), PrevClose, Volume, Value, Trades, IndexURL.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd

from .errors import AmbiguousTicker, InstrumentNotFound, DataSourceError
from .utils import coerce_id, jalali_str, ticker_key

HISTORY_MAP = {"dEven": "Date", "priceFirst": "Open", "priceMax": "High",
    "priceMin": "Low", "pClosing": "Close", "pDrCotVal": "Last",
    "priceYesterday": "PrevClose", "qTotTran5J": "Volume", "qTotCap": "Value",
    "zTotTran": "Trades"}
PRICES = ["Open", "High", "Low", "Close", "Last", "PrevClose"]
VALUE_COLUMNS = PRICES + ["Volume", "Value", "Trades"]
HISTORY_COLUMNS = ["Date", "JDate", *VALUE_COLUMNS, "IndexURL"]


def _empty_history():
    frame = pd.DataFrame({col: pd.Series(dtype="float64") for col in HISTORY_COLUMNS})
    frame["Date"] = pd.Series(dtype="datetime64[ns]")
    frame["JDate"] = pd.Series(dtype="object")
    frame["IndexURL"] = pd.Series(dtype="object")
    return frame[HISTORY_COLUMNS]


def add_jalali(frame: pd.DataFrame) -> pd.DataFrame:
    frame["JDate"] = frame["Date"].map(jalali_str).astype("object")
    return frame


def filter_traded(frame: pd.DataFrame, traded_only: bool) -> pd.DataFrame:
    """Drop days without trades (Trades == 0) only when asked to."""
    if traded_only and not frame.empty:
        frame = frame.loc[pd.to_numeric(frame["Trades"], errors="coerce").fillna(0) > 0]
        frame = frame.reset_index(drop=True)
    return frame


def parse_history(items, instrument_id, *, traded_only=False):
    """Parse ``GetClosingPriceDailyList``. ``traded_only=False`` keeps every day."""
    if not isinstance(items, list):
        raise DataSourceError("ClosingPriceDaily must be a list")
    if not items:
        return _empty_history()
    df = pd.DataFrame(items)
    required = list(HISTORY_MAP)
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise DataSourceError(f"Daily history missing required fields: {missing}")
    df = df[required].rename(columns=HISTORY_MAP)
    df["Date"] = pd.to_datetime(df["Date"].astype(str), format="%Y%m%d", errors="coerce")
    for col in VALUE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df = df.drop_duplicates(subset="Date", keep="last").reset_index(drop=True)
    df = filter_traded(df, traded_only)
    df["IndexURL"] = coerce_id(instrument_id)
    add_jalali(df)
    return df[HISTORY_COLUMNS]


def parse_adjustments(items):
    if not isinstance(items, list):
        raise DataSourceError("PriceAdjust must be a list")
    result = []
    for row in items:
        try:
            event_date = pd.to_datetime(str(row["dEven"]), format="%Y%m%d")
            raw = float(row["pClosingNotAdjusted"])
            adj = float(row["pClosing"])
            if raw <= 0 or adj <= 0:
                raise ValueError("invalid coefficient")
            result.append((event_date, adj / raw))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataSourceError(f"Invalid price adjustment: {row!r}") from exc
    frame = pd.DataFrame(result, columns=["Date", "Factor"])
    if frame.empty:
        frame["Date"] = pd.Series(dtype="datetime64[ns]")
        frame["Factor"] = pd.Series(dtype="float64")
        return frame
    return frame.sort_values("Date").drop_duplicates("Date", keep="last").reset_index(drop=True)


def apply_adjustments(history, events):
    """Back-adjust prices before each corporate action; latest prices stay original.

    Event factor = pClosing / pClosingNotAdjusted (from GetPriceAdjustList).
    A price on day *d* is multiplied by every factor whose event date is
    strictly after *d*. Volume, value and trade count are never changed.
    """
    output = history.copy()
    if output.empty:
        output["AdjCoef"] = pd.Series(dtype=float)
    elif events is None or events.empty:
        output["AdjCoef"] = 1.0
    else:
        ordered = events.sort_values("Date")
        when = ordered["Date"].to_numpy(dtype="datetime64[ns]")
        factors = ordered["Factor"].to_numpy(dtype=float)
        after = np.searchsorted(when, output["Date"].to_numpy(dtype="datetime64[ns]"), side="right")
        cumulative = np.r_[np.cumprod(factors[::-1])[::-1], 1.0]
        output["AdjCoef"] = cumulative[after]
    for col in PRICES:
        output[f"Adj{col}"] = pd.to_numeric(output[col], errors="coerce") * output["AdjCoef"]
    return output


class History:
    def __init__(self, client, directory=None, *, traded_only=False):
        self.client = client
        self.directory = directory
        self.traded_only = bool(traded_only)
        self.last_errors: dict[str, str] = {}

    def resolve(self, ticker=None, instrument_id=None):
        if instrument_id is not None:
            return coerce_id(instrument_id)
        if ticker is None:
            raise ValueError("Supply ticker= or instrument_id=")
        if self.directory is None:
            raise InstrumentNotFound("A TDA directory is needed to resolve ticker names")
        found = self.directory.find(ticker)
        if found.empty:
            raise InstrumentNotFound(f"Ticker not present in TDA: {ticker}")
        if len(found) != 1:
            raise AmbiguousTicker(f"Ticker {ticker!r} matches {list(found.index)}; use instrument_id=")
        return str(found.index[0])

    def fetch(self, *, ticker=None, instrument_id=None, adjusted=False, last=0,
              traded_only=None, include_metadata=True):
        """Online daily history. ``traded_only=None`` -> library default (keep all days)."""
        traded_only = self.traded_only if traded_only is None else bool(traded_only)
        iid = self.resolve(ticker, instrument_id)
        frame = parse_history(self.client.daily_prices(iid, last=last), iid, traded_only=traded_only)
        if adjusted:
            frame = apply_adjustments(frame, parse_adjustments(self.client.price_adjustments(iid)))
        if include_metadata and self.directory is not None:
            directory = self.directory.instruments()
            if iid in directory.index:
                for col in ("Ticker", "Name", "MarketType", "Industry", "Type", "StockQty"):
                    frame[col] = directory.at[iid, col]
        return frame

    def fetch_many(self, *, tickers=None, instrument_ids=None, adjusted=False,
                   workers=4, on_error="raise", **kwargs):
        if (tickers is None) == (instrument_ids is None):
            raise ValueError("Supply exactly one of tickers= or instrument_ids=")
        if on_error not in ("raise", "skip"):
            raise ValueError("on_error must be 'raise' or 'skip'")
        ids = ([self.resolve(ticker=x) for x in tickers] if tickers is not None
               else [self.resolve(instrument_id=x) for x in instrument_ids])
        values, errors = {}, {}
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            futures = {pool.submit(self.fetch, instrument_id=i, adjusted=adjusted, **kwargs): i
                       for i in dict.fromkeys(ids)}
            for future in as_completed(futures):
                instrument = futures[future]
                try:
                    values[instrument] = future.result()
                except Exception as exc:
                    errors[instrument] = str(exc)
        self.last_errors = errors
        if errors and on_error == "raise":
            raise DataSourceError(f"Failed to fetch {len(errors)} instruments: {errors}")
        frames = [values[i] for i in dict.fromkeys(ids) if i in values]
        return pd.concat(frames, ignore_index=True) if frames else _empty_history()
