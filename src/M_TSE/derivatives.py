"""Option/futures market data; never drops contracts without a matching underlying.

Contract details (underlying, strike, expiry) are still parsed from the
contract name, as in the original code.
"""
from __future__ import annotations
import re
from datetime import date
import pandas as pd
from .utils import normalize, parse_persian_date, ticker_key
from .market import filter_type, CALL_CODES, _code_text

UNDERLYING_ALIASES = {
    "آگاه": "پتروآگاه", "رو": "بهین رو", "حافرین": "حآفرین",
    "وب": "های وب", "وزن": "هم وزن", "نارنج": "نارنج اهرم",
    "فارماکیان": "فارما کیان",
}
_ALIAS_BY_KEY = {ticker_key(k): v for k, v in UNDERLYING_ALIASES.items()}

# Legacy name format: "... خودرو-2500-1405/09/25".
LAST_DATE = re.compile(r"(?P<date>1[34]\d{2}[/-]?\d{1,2}[/-]?\d{1,2}|\d{6})(?:\s*)$")


def _name_contract(name: object):
    value = normalize(name)
    try:
        head, strike, maturity = [part.strip() for part in value.rsplit("-", 2)]
    except ValueError:
        return None, None, None
    try:
        expiry = parse_persian_date(maturity)
        strike_price = float(normalize(strike).replace(",", ""))
        underlying = normalize(head.split()[-1]) if head.split() else None
        return _ALIAS_BY_KEY.get(ticker_key(underlying), underlying), strike_price, expiry
    except (ValueError, IndexError):
        return None, None, None


def resolve_underlying(name: object, parsed, known_keys) -> object:
    """Underlying ticker tolerant of multi-word tickers (e.g. «جوانه کوچک», options ضجوا…).

    Every word-suffix of the contract-name head is tried, longest first, against ``known_keys``
    (``ticker_key`` of the board's tickers); the first match wins. Otherwise ``parsed`` (last word +
    UNDERLYING_ALIASES) is kept.
    """
    if not isinstance(name, str) or not known_keys:
        return parsed
    value = normalize(name)
    if value.count("-") < 2:
        return parsed
    words = value.rsplit("-", 2)[0].split()[1:]      # drop "اختیارخ" / "اختیارف"
    for k in range(len(words), 0, -1):
        candidate = " ".join(words[-k:])
        if ticker_key(candidate) in known_keys:
            return candidate
    return parsed


def add_contract_columns(frame: pd.DataFrame, *, today=None, known_tickers=None) -> pd.DataFrame:
    """OptionKind, Underlying, Strike, Expiry, DaysToExpiry (calendar days).

    ``known_tickers``: optional iterable of underlying tickers on the board; when given, multi-word
    underlyings are resolved against it (see ``resolve_underlying``).
    """
    options = frame.copy()
    options["OptionKind"] = options["Type"].map(
        lambda typ: "call" if _code_text(typ) in CALL_CODES else "put").astype("object")
    parsed = options["Name"].map(_name_contract)
    options["Underlying"] = parsed.map(lambda x: x[0]).astype("object")
    if known_tickers is not None:
        keys = {ticker_key(t) for t in known_tickers if isinstance(t, str)}
        options["Underlying"] = [resolve_underlying(n, u, keys)
                                 for n, u in zip(options["Name"], options["Underlying"])]
        options["Underlying"] = options["Underlying"].astype("object")
    options["Strike"] = pd.to_numeric(parsed.map(lambda x: x[1]), errors="coerce")
    options["Expiry"] = parsed.map(lambda x: x[2]).astype("object")
    now = today or date.today()
    options["DaysToExpiry"] = options["Expiry"].map(
        lambda x: (x - now).days if isinstance(x, date) else pd.NA).astype("Int64")
    return options


class Derivatives:
    def __init__(self, market):
        self.market = market

    def options(self, *, kind="both", depth=True, underlying=True, today=None,
                source=None) -> pd.DataFrame:
        if kind not in ("both", "call", "put"):
            raise ValueError("kind must be 'both', 'call', or 'put'")
        snapshot = self.market.snapshot(depth=depth, source=source)
        types = {"both": ["CallOption", "PutOption"],
                 "call": ["CallOption"], "put": ["PutOption"]}[kind]
        base = filter_type(snapshot, ["Stock", "Fund", "CommodityFund"]) if underlying else None
        options = add_contract_columns(filter_type(snapshot, types), today=today,
                                       known_tickers=None if base is None else base["Ticker"])
        if underlying:
            # If a ticker occurs more than once, prefer the main-board listing.
            base = base.assign(_key=base["Ticker"].map(ticker_key),
                               _primary=base["IRcode"].astype(str).str.endswith("1").astype(int))
            base = base.sort_values("_primary", ascending=False).drop_duplicates("_key")
            by_key = base.reset_index().set_index("_key")
            keys = options["Underlying"].map(ticker_key)
            for source_col, output in (("Close", "UnderlyingClose"), ("Last", "UnderlyingLast"),
                                       ("Volume", "UnderlyingVolume")):
                options[output] = keys.map(by_key[source_col])
            options["UnderlyingID"] = keys.map(by_key["IndexURL"]).astype("object")
        return options

    def calls(self, **kwargs):
        return self.options(kind="call", **kwargs)

    def puts(self, **kwargs):
        return self.options(kind="put", **kwargs)

    def futures(self, *, depth=True, source=None):
        return self.market.by_type(["Future", "CommodityDerivative"], depth=depth, source=source)
