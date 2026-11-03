"""Market watch: new cdn.tsetmc.com API (default) + legacy MarketWatchInit parser.

Column convention (identical in market, derivatives and history modules):

    Open      first trade price of the day               (pf / priceFirst)
    High/Low  day range                                  (pmx,pmn / priceMax,priceMin)
    Close     *final* price, قیمت پایانی — the volume-weighted
              price that sets tomorrow's base             (pcl / pClosing)
    Last      last traded price, آخرین معامله             (pdv / pDrCotVal)
    PrevClose previous day's final price                 (py / priceYesterday)
    Trades / Volume / Value                              (ztt,qtj,qtc / zTotTran,qTotTran5J,qTotCap)
"""
from __future__ import annotations

import re
import pandas as pd

from .errors import DataSourceError
from .utils import normalize, coerce_id, is_valid_id

BOARD_FIELDS = ["IRcode", "Ticker", "Name", "LastTrade", "Open", "Close", "Last",
    "Trades", "Volume", "Value", "Low", "High", "PrevClose", "EPS",
    "BaseVolume", "IDK_1", "MarketType", "Industry", "MaxAlw", "MinAlw",
    "StockQty", "Type", "Nav", "OpenInterest", "Board", "MarketCode"]
# Legacy MarketWatchInit order of the 22 values after the ID.
_OLD_ORDER = ["IRcode", "Ticker", "Name", "LastTrade", "Open", "Close", "Last",
    "Trades", "Volume", "Value", "Low", "High", "PrevClose", "EPS",
    "BaseVolume", "IDK_1", "MarketType", "Industry", "MaxAlw", "MinAlw",
    "StockQty", "Type"]
# TDA (identifier directory) columns — unchanged legacy Excel layout.
BASIC_COLUMNS = ["IRcode", "Ticker", "Name", "IDK_1", "MarketType", "Industry", "StockQty", "Type"]
NUMERIC = ["Open", "Close", "Last", "Trades", "Volume", "Value", "Low", "High",
           "PrevClose", "EPS", "BaseVolume", "MaxAlw", "MinAlw", "StockQty", "Nav", "OpenInterest"]
DEPTH_METRICS = ("SellCount", "BuyCount", "BuyPrice", "SellPrice", "BuyVolume", "SellVolume")
DEPTH_COLUMNS = [f"{metric}{level}" for level in range(1, 6) for metric in DEPTH_METRICS]

MARKET_OVERVIEW_FIELDS = ["LastTradeDate", "TSE_Situation", "TEPIX", "TEPIXChange",
    "TSE_MarketCap", "TSE_Volume", "TSE_Value", "TSE_NumTransaction",
    "IFB_Situation", "IFB_Volume", "IFB_Value", "IFB_NumTransaction",
    "Dev_Situation", "Dev_Volume", "Dev_Value", "Dev_NumTransaction"]
TYPE_CODES = {
 "Sukuk": ["208"], "Stock": ["300", "303", "309", "313"],
 "CorporateBond": ["301"], "Future": ["304"], "Fund": ["305"],
 "Akhza": ["306"], "Teseh": ["307"], "Salf": ["308"],
 "CallOption": ["311", "320"], "PutOption": ["312", "321"],
 "CommodityFund": ["380"], "Priority": ["40"],
 "CommodityDerivative": ["701"], "Morabehe": ["706"],
}
CALL_CODES = set(TYPE_CODES["CallOption"])
PUT_CODES = set(TYPE_CODES["PutOption"])

# new API JSON key -> library column
_NEW_MAP = {"insID": "IRcode", "lva": "Ticker", "lvc": "Name", "hEven": "LastTrade",
            "pf": "Open", "pcl": "Close", "pdv": "Last", "ztt": "Trades",
            "qtj": "Volume", "qtc": "Value", "pmn": "Low", "pmx": "High",
            "py": "PrevClose", "eps": "EPS", "bv": "BaseVolume", "vc": "IDK_1",
            "csv": "Industry", "pMax": "MaxAlw", "pMin": "MinAlw", "ztd": "StockQty",
            "yVal": "Type", "flow": "MarketType", "pRedTran": "Nav", "buyOP": "OpenInterest",
            "cGrValCot": "Board", "yMarNSC": "MarketCode"}
# Instruments for which open interest is meaningful (options, futures, commodity derivatives).
_OI_CODES = set(TYPE_CODES["CallOption"]) | set(TYPE_CODES["PutOption"]) | {"304", "701"}


def _code_text(value):
    """'300.0' / 300 / 3e2 -> '300'; blanks -> None."""
    if value is None:
        return None
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text or text.lower() in ("none", "nan", "<na>"):
        return None
    return re.sub(r"\.0+$", "", text)


def infer_type_from_name(name) -> str | None:
    """Last-resort type for options when neither archive nor API supplies it."""
    value = normalize(name)
    if value.startswith("اختیارخ"):
        return "311"
    if value.startswith("اختیارف"):
        return "312"
    return None


def _finish(frame: pd.DataFrame, *, numeric: bool) -> pd.DataFrame:
    frame = frame.loc[~frame.index.duplicated(keep="last")]
    frame.index = frame.index.astype(str)
    frame.index.name = "IndexURL"
    for column in BOARD_FIELDS:
        if column not in frame:
            frame[column] = pd.NA
    frame["Ticker"] = frame["Ticker"].map(normalize)
    frame["Name"] = frame["Name"].map(normalize)
    for column in ("Type", "MarketType", "Industry", "Board", "MarketCode"):
        frame[column] = frame[column].map(_code_text).astype("object")
    if numeric:
        for col in NUMERIC:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        # NAV only exists for funds (0/blank elsewhere); open interest only for derivatives.
        frame["Nav"] = frame["Nav"].where(frame["Nav"] > 0)
        frame["OpenInterest"] = frame["OpenInterest"].where(frame["Type"].isin(_OI_CODES))
    else:
        frame["StockQty"] = frame["StockQty"].map(_code_text).astype("object")
    return frame[BOARD_FIELDS]


# ------------------------------------------------------------------ new API
def parse_market_watch(rows: list[dict], *, numeric=True) -> pd.DataFrame:
    """Parse the new ``ClosingPrice/GetMarketWatch`` rows.

    Current responses carry Type (yVal), MarketType (flow), NAV (pRedTran),
    open interest (buyOP) and board code (cGrValCot). Older responses without
    them are completed from the local archive / ``GetInstrumentInfo``.
    """
    if not isinstance(rows, list) or not rows:
        raise DataSourceError("No market-watch rows in response")
    records = []
    for row in rows:
        if not isinstance(row, dict) or not is_valid_id(row.get("insCode")):
            continue
        rec = {col: row.get(key) for key, col in _NEW_MAP.items()}
        rec["IndexURL"] = coerce_id(row["insCode"])
        if rec.get("Industry") is not None:
            rec["Industry"] = str(rec["Industry"]).strip()
        records.append(rec)
    if not records:
        raise DataSourceError("Cannot parse market-watch rows (unsupported TSETMC API?)")
    frame = pd.DataFrame(records).set_index("IndexURL")
    return _finish(frame, numeric=numeric)


def parse_market_watch_depth(rows: list[dict]) -> pd.DataFrame:
    """Five-level order book from ``blDs`` of the new market watch."""
    records: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict) or not is_valid_id(row.get("insCode")):
            continue
        iid = coerce_id(row["insCode"])
        for level in row.get("blDs") or []:
            try:
                n = int(level.get("n"))
            except (TypeError, ValueError):
                continue
            if not 1 <= n <= 5:
                continue
            rec = records.setdefault(iid, {})
            for metric, key in (("SellCount", "zmo"), ("BuyCount", "zmd"), ("BuyPrice", "pmd"),
                                ("SellPrice", "pmo"), ("BuyVolume", "qmd"), ("SellVolume", "qmo")):
                rec[f"{metric}{n}"] = pd.to_numeric(level.get(key), errors="coerce")
    if not records:
        return pd.DataFrame(columns=DEPTH_COLUMNS, index=pd.Index([], name="IndexURL"))
    return pd.DataFrame.from_dict(records, orient="index").reindex(columns=DEPTH_COLUMNS).rename_axis("IndexURL")


def parse_overview_new(tse: dict, ifb: dict | None = None) -> pd.DataFrame:
    """One-row overview from ``MarketData/GetMarketOverview/1`` (and /2)."""
    if not isinstance(tse, dict):
        raise DataSourceError("Malformed market overview")
    ifb = ifb if isinstance(ifb, dict) else {}
    num = lambda d, k: pd.to_numeric(d.get(k), errors="coerce")
    row = {
        "LastTradeDate": _code_text(tse.get("marketActivityDEven")),
        "TSE_Situation": tse.get("marketStateTitle") or tse.get("marketState"),
        "TEPIX": num(tse, "indexLastValue"), "TEPIXChange": num(tse, "indexChange"),
        "TEPIX_EW": num(tse, "indexEqualWeightedLastValue"),
        "TEPIX_EWChange": num(tse, "indexEqualWeightedChange"),
        "TSE_MarketCap": num(tse, "marketValue"),
        "TSE_Volume": num(tse, "marketActivityQTotTran"),
        "TSE_Value": num(tse, "marketActivityQTotCap"),
        "TSE_NumTransaction": num(tse, "marketActivityZTotTran"),
        "TSE_LastTradeTime": _code_text(tse.get("marketActivityHEven")),
        "IFB_Situation": ifb.get("marketStateTitle") or ifb.get("marketState"),
        "IFX": num(ifb, "indexLastValue"), "IFXChange": num(ifb, "indexChange"),
        "IFB_MarketCap": num(ifb, "marketValue"),
        "IFB_Volume": num(ifb, "marketActivityQTotTran"),
        "IFB_Value": num(ifb, "marketActivityQTotCap"),
        "IFB_NumTransaction": num(ifb, "marketActivityZTotTran"),
    }
    return pd.DataFrame([row])


# ------------------------------------------------------------------ legacy API
def parse_overview(sections: list[str]) -> pd.DataFrame:
    """One-row top-level TSE/IFB market overview (legacy sections[1])."""
    if len(sections) < 2:
        raise DataSourceError("No market summary section")
    clean = re.sub(r"<[^>]+>", "", sections[1]).strip()
    values = clean.split(",")
    if values and values[-1] == "":
        values.pop()
    if len(values) != len(MARKET_OVERVIEW_FIELDS):
        raise DataSourceError(f"Unsupported market overview layout: {len(values)} fields")
    frame = pd.DataFrame([values], columns=MARKET_OVERVIEW_FIELDS)
    for field in MARKET_OVERVIEW_FIELDS:
        if field not in ("LastTradeDate", "TSE_Situation", "IFB_Situation", "Dev_Situation"):
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame


def parse_watch(sections: list[str], *, numeric=True) -> pd.DataFrame:
    """Legacy old.tsetmc.com MarketWatchInit rows."""
    if len(sections) < 3:
        raise DataSourceError("No market-watch rows in response")
    rows = []
    for row in sections[2].split(";"):
        fields = row.split(",")
        if len(fields) < 23 or not is_valid_id(fields[0].strip()):
            continue
        values = fields[1:]
        # 22 values after the ID, or 25 (NAV, open interest, board code).
        if len(values) not in (22, 25):
            continue
        row_dict = dict(zip(_OLD_ORDER, values[:22]))
        if len(values) == 25:
            row_dict.update(dict(zip(["Nav", "OpenInterest", "Board"], values[22:25])))
        row_dict["IndexURL"] = fields[0].strip()
        rows.append(row_dict)
    if not rows:
        raise DataSourceError("Cannot parse market-watch rows (unsupported TSETMC protocol?)")
    return _finish(pd.DataFrame(rows).set_index("IndexURL"), numeric=numeric)


def parse_depth(sections: list[str]) -> pd.DataFrame:
    if len(sections) < 4 or not sections[3].strip():
        return pd.DataFrame(columns=DEPTH_COLUMNS, index=pd.Index([], name="IndexURL"))
    records: dict[str, dict] = {}
    for line in sections[3].split(";"):
        parts = line.split(",")
        if len(parts) < 8:
            continue
        iid, level_str = parts[0].strip(), parts[1].strip()
        try:
            level = int(level_str)
        except ValueError:
            continue
        if not is_valid_id(iid) or not 1 <= level <= 5:
            continue
        for column, value in zip(DEPTH_METRICS, parts[2:8]):
            records.setdefault(iid, {})[f"{column}{level}"] = pd.to_numeric(value, errors="coerce")
    return pd.DataFrame.from_dict(records, orient="index").reindex(columns=DEPTH_COLUMNS).rename_axis("IndexURL")


# ------------------------------------------------------------------ filtering
def filter_type(frame: pd.DataFrame, types, *, primary_board_only=False) -> pd.DataFrame:
    """Filter by named class or raw TSETMC type code; no hidden board filtering."""
    if isinstance(types, (str, int)):
        types = [types]
    if not types:
        return frame.copy()
    codes = set()
    for kind in types:
        if str(kind) in TYPE_CODES:
            codes.update(TYPE_CODES[str(kind)])
        elif str(kind).isdigit():
            codes.add(str(kind))
        else:
            raise ValueError(f"Unknown security class {kind!r}; options: {list(TYPE_CODES)}")
    type_values = frame["Type"].map(_code_text)
    mask = type_values.isin(codes)
    if "40" in codes:
        mask |= type_values.map(lambda x: isinstance(x, str) and x.startswith("40"))
    result = frame.loc[mask]
    if primary_board_only:
        result = result.loc[result["IRcode"].astype(str).str.endswith("1")]
    return result.copy()


# ------------------------------------------------------------------ facade
class Market:
    """Online market watch.

    ``registry``: an :class:`Archive` used to fill Type/MarketType that the new
    API does not return. ``enrich``: for IDs unknown to the registry, call
    ``GetInstrumentInfo`` (at most ``max_enrich`` per snapshot, cached).
    """

    def __init__(self, client, registry=None, *, enrich=True, max_enrich=300):
        self.client = client
        self.registry = registry
        self.enrich = enrich
        self.max_enrich = int(max_enrich)
        self._info_cache: dict[str, dict] = {}
        self.last_source = None

    def _source(self, source):
        source = source or getattr(self.client, "market_source", "old")
        if not hasattr(self.client, "market_watch"):
            return "old"
        return source

    # -- metadata completion for the new API
    def _complete_metadata(self, board: pd.DataFrame) -> pd.DataFrame:
        if self.registry is not None:
            known = self.registry.instruments()
            known = known.loc[known.index.isin(board.index)]
            for col in ("Type", "MarketType", "Industry"):
                if col not in known or known.empty:
                    continue
                board[col] = board[col].astype("object")
                fill = pd.Series(board.index.map(known[col]), index=board.index, dtype="object")
                missing = board[col].isna()
                board.loc[missing, col] = fill[missing]
        missing_type = board.index[board["Type"].isna()]
        if self.enrich and len(missing_type) and hasattr(self.client, "instrument_info"):
            for iid in list(missing_type)[: self.max_enrich]:
                info = self._info_cache.get(iid)
                if info is None:
                    try:
                        info = self.client.instrument_info(iid)
                    except Exception:
                        info = {}
                    self._info_cache[iid] = info
                if info:
                    board.at[iid, "Type"] = _code_text(info.get("yVal"))
                    if pd.isna(board.at[iid, "MarketType"]):
                        board.at[iid, "MarketType"] = _code_text(info.get("flow"))
                    sector = (info.get("sector") or {}).get("cSecVal")
                    if pd.isna(board.at[iid, "Industry"]) and sector:
                        board.at[iid, "Industry"] = str(sector).strip()
        still = board["Type"].isna()
        if still.any():
            board.loc[still, "Type"] = board.loc[still, "Name"].map(infer_type_from_name)
        for column in ("Type", "MarketType", "Industry"):
            board[column] = board[column].map(_code_text).astype("object")
        return board

    def overview(self, *, source=None):
        source = self._source(source)
        if source in ("new", "auto"):
            try:
                tse = self.client.market_overview(1)
                try:
                    ifb = self.client.market_overview(2)
                except DataSourceError:
                    ifb = None
                self.last_source = "new"
                return parse_overview_new(tse, ifb)
            except DataSourceError:
                if source == "new":
                    raise
        self.last_source = "old"
        return parse_overview(self.client.market_sections())

    def snapshot(self, *, depth=False, numeric=True, source=None):
        """All instruments of the current market watch (index = IndexURL)."""
        source = self._source(source)
        if source in ("new", "auto"):
            try:
                rows = self.client.market_watch()
                board = self._complete_metadata(parse_market_watch(rows, numeric=numeric))
                if depth:
                    board = board.join(parse_market_watch_depth(rows), how="left")
                self.last_source = "new"
                return board
            except DataSourceError:
                if source == "new":
                    raise
        sections = self.client.market_sections()
        board = parse_watch(sections, numeric=numeric)
        if depth:
            board = board.join(parse_depth(sections), how="left")
        self.last_source = "old"
        return board

    def stream(self, *, interval=1.0, duration=None, depth=True, types=None,
               only_changes=True, source="new"):
        """Poll the market watch repeatedly and yield ``(timestamp, frame)``.

        ``only_changes=True`` yields only rows whose prices, volume or order
        book changed since the previous poll (all rows on the first poll).
        ``duration`` in seconds (None = until interrupted). Errors of a single
        poll are skipped; the stream continues.
        """
        import time
        from datetime import datetime
        watch = BOARD_FIELDS[3:13] + (DEPTH_COLUMNS if depth else []) + ["OpenInterest", "Nav"]
        previous = None
        start = time.monotonic()
        while duration is None or time.monotonic() - start < duration:
            tick = time.monotonic()
            try:
                board = self.snapshot(depth=depth, source=source)
            except DataSourceError:
                board = None
            if board is not None:
                if types:
                    board = filter_type(board, types)
                if only_changes and previous is not None:
                    cols = [c for c in watch if c in board and c in previous]
                    old = previous.reindex(board.index)[cols]
                    changed = ~(board[cols].eq(old) | (board[cols].isna() & old.isna())).all(axis=1)
                    out = board.loc[changed]
                else:
                    out = board
                previous = board
                yield datetime.now(), out
            time.sleep(max(0.0, interval - (time.monotonic() - tick)))

    def by_type(self, types, *, depth=False, primary_board_only=False, source=None):
        return filter_type(self.snapshot(depth=depth, source=source), types,
                           primary_board_only=primary_board_only)
