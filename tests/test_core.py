from datetime import date
from pathlib import Path
import sqlite3
import pandas as pd
import pytest

from M_TSE import M_TSE, TSEMarketKit, Archive, AmbiguousTicker, DataSourceError
from M_TSE.market import (BASIC_COLUMNS, parse_watch, parse_depth, filter_type,
                          parse_market_watch, parse_market_watch_depth, parse_overview_new)
from M_TSE.history import parse_history, parse_adjustments, apply_adjustments
from M_TSE.derivatives import _name_contract
from M_TSE.utils import (normalize, ticker_key, coerce_id, parse_persian_date,
                         gregorian_to_jalali, jalali_to_gregorian, to_excel)

IID_A = "11111111111111111"
IID_B = "22222222222222222"
IID_C = "33333333333333333"
LONG_ID = "65883838195688438"   # changes if ever converted to float


# ---------------------------------------------------------------- fixtures
def make_line(iid, ticker, typ, name):
    cols = ["IRO1", ticker, name, "20261102", "100", "100", "101", "1", "1000", "101000",
            "95", "110", "98", "12", "100", "?", "1", "42", "110", "90", "1000000", typ]
    assert len(cols) == 22
    return ",".join([iid, *cols])


@pytest.fixture
def sections():
    lines = [make_line(IID_A, "خودرو", "300", "ایران خودرو"),
             make_line(IID_B, "ضخود1234", "311", "اختيارخ خودرو-2500-1405/09/25"),
             make_line(IID_C, "ضخود5678", "312", "اختیارف خودرو-3000-1405/10/20")]
    depth = [f"{IID_A},1,2,3,100,101,1000,1500", f"{IID_B},1,1,2,22,23,400,500"]
    return ["", "overview", ";".join(lines), ";".join(depth)]


def new_row(iid, ticker, name, *, pcl=100.0, pdv=101.0, ztt=5.0):
    """Row in the shape of cdn.tsetmc.com ClosingPrice/GetMarketWatch."""
    return {"insCode": iid, "insID": "IRO1TEST0001", "lva": ticker, "lvc": name,
            "hEven": 122930, "pf": 99.0, "pcl": pcl, "pdv": pdv, "ztt": ztt,
            "qtj": 1000.0, "qtc": 101000.0, "pmn": 95.0, "pmx": 110.0, "py": 98.0,
            "eps": 12.0, "bv": 100.0, "vc": 7, "csv": "34 ", "pMax": 110.0, "pMin": 90,
            "ztd": 1000000.0, "pe": "8.1", "pClosing": 0.0, "pDrCotVal": 0.0,
            "blDs": [{"n": 1, "qmd": 400, "zmd": 2, "pmd": 99.0, "pmo": 102.0, "zmo": 1, "qmo": 500},
                     {"n": 2, "qmd": 0, "zmd": 0, "pmd": 0.0, "pmo": 0.0, "zmo": 0, "qmo": 0}]}


@pytest.fixture
def new_rows():
    # Arabic ي/ك exactly as TSETMC sends them.
    return [new_row(IID_A, "فملي", "ملي‌ صنايع‌ مس‌ ايران‌", pcl=8000.0, pdv=8050.0),
            new_row(IID_B, "ضملي1234", "اختيارخ فملي-9000-1405/09/25"),
            new_row(IID_C, "طملي1234", "اختيارف فملي-7000-1405/09/25")]


class DummyClient:
    market_source = "old"

    def __init__(self, sections=None, rows=None, info=None):
        self.sections = sections or []
        self.rows = rows
        self.info = info or {}
        self.info_calls = 0
        self.fail = set()
        self.daily_calls = 0
        if rows is not None:
            self.market_source = "new"

    def market_sections(self):
        return self.sections

    def market_watch(self):
        if self.rows is None:
            raise DataSourceError("new API unavailable")
        return self.rows

    def market_overview(self, flow=1):
        raise DataSourceError("offline")

    def instrument_info(self, iid):
        self.info_calls += 1
        if iid not in self.info:
            raise DataSourceError("no info")
        return self.info[iid]

    def daily_prices(self, instrument_id, last=0):
        self.daily_calls += 1
        if instrument_id in self.fail:
            raise DataSourceError("offline source failure")
        return [
            {"dEven": 20260101, "priceMax": 100, "priceMin": 80, "pClosing": 90,
             "pDrCotVal": 89, "priceFirst": 85, "priceYesterday": 88, "qTotCap": 1000,
             "qTotTran5J": 100, "zTotTran": 2},
            {"dEven": 20260201, "priceMax": 200, "priceMin": 160, "pClosing": 180,
             "pDrCotVal": 175, "priceFirst": 165, "priceYesterday": 170, "qTotCap": 2000,
             "qTotTran5J": 110, "zTotTran": 3},
            {"dEven": 20260301, "priceMax": 180, "priceMin": 180, "pClosing": 180,
             "pDrCotVal": 180, "priceFirst": 180, "priceYesterday": 180, "qTotCap": 0,
             "qTotTran5J": 0, "zTotTran": 0},   # no trade that day
        ]

    def price_adjustments(self, instrument_id):
        return [{"dEven": 20260115, "pClosing": 5, "pClosingNotAdjusted": 10}]


# ---------------------------------------------------------------- legacy parser
def test_legacy_parser_market_and_depth(sections):
    board = parse_watch(sections)
    assert len(board) == 3
    assert board.loc[IID_A, "Volume"] == 1000
    assert board.loc[IID_A, "Close"] == 100 and board.loc[IID_A, "Last"] == 101
    assert len(filter_type(board, "Stock")) == 1
    assert len(filter_type(board, "CallOption")) == 1
    assert len(filter_type(board, "PutOption")) == 1
    assert len(filter_type(board, "311")) == 1
    assert parse_depth(sections).loc[IID_B, "BuyVolume1"] == 400
    with pytest.raises(ValueError):
        filter_type(board, "INVALID_TYPE")


def test_bad_market_raises():
    with pytest.raises(DataSourceError):
        parse_watch(["", "", "broken"])
    with pytest.raises(DataSourceError):
        parse_market_watch([])


# ---------------------------------------------------------------- new API
def test_new_api_parser_columns_and_depth(new_rows):
    board = parse_market_watch(new_rows)
    assert list(board.index) == [IID_A, IID_B, IID_C]
    row = board.loc[IID_A]
    assert row["Ticker"] == "فملی"                     # Arabic ي normalized
    assert row["Name"] == "ملی صنایع مس ایران"          # half-spaces before spaces removed
    assert row["Close"] == 8000 and row["Last"] == 8050   # Close = pcl (final), Last = pdv
    assert row["Industry"] == "34"
    depth = parse_market_watch_depth(new_rows)
    assert depth.loc[IID_A, "BuyVolume1"] == 400 and depth.loc[IID_A, "SellPrice1"] == 102


def test_new_api_type_from_registry_info_and_name(new_rows, tmp_path):
    info = {IID_A: {"yVal": "300", "flow": 1, "sector": {"cSecVal": "27 "}}}
    client = DummyClient(rows=new_rows, info=info)
    tse = M_TSE(tmp_path, client=client, seed=False)
    board = tse.market.snapshot(depth=True)
    assert tse.market.last_source == "new"
    assert board.loc[IID_A, "Type"] == "300"          # from GetInstrumentInfo
    assert board.loc[IID_A, "MarketType"] == "1"
    assert board.loc[IID_B, "Type"] == "311"          # inferred from اختيارخ
    assert board.loc[IID_C, "Type"] == "312"          # inferred from اختيارف
    tse.update_tda()
    calls_before = client.info_calls
    tse2 = M_TSE(tmp_path, client=client, seed=False)  # fresh cache, registry now knows types
    tse2.market.snapshot()
    assert client.info_calls == calls_before          # no extra info requests


def test_auto_source_falls_back_to_old(sections, tmp_path):
    client = DummyClient(sections=sections)
    client.market_source = "auto"
    tse = M_TSE(tmp_path, client=client, seed=False)
    assert len(tse.market.snapshot()) == 3
    assert tse.market.last_source == "old"
    client.market_source = "new"
    with pytest.raises(DataSourceError):
        tse.market.snapshot()


def test_new_overview_parser():
    tse = {"indexLastValue": 2279681.78, "indexChange": 8639.39, "marketActivityDEven": 20230603,
           "marketActivityZTotTran": 492208, "marketActivityQTotCap": 6.7e13,
           "marketActivityQTotTran": 8.9e9, "marketState": "F", "marketValue": 8.4e16,
           "marketStateTitle": "بسته"}
    frame = parse_overview_new(tse, {"indexLastValue": 20000, "marketStateTitle": "بسته"})
    assert frame.at[0, "TEPIX"] == 2279681.78
    assert frame.at[0, "LastTradeDate"] == "20230603"
    assert frame.at[0, "IFX"] == 20000


def test_options_underlying_matches_despite_arabic_letters(new_rows, tmp_path):
    info = {IID_A: {"yVal": "300", "flow": 1}}
    tse = M_TSE(tmp_path, client=DummyClient(rows=new_rows, info=info), seed=False)
    calls = tse.derivatives.calls(today=date(2026, 11, 2))
    assert len(calls) == 1
    row = calls.iloc[0]
    assert row["Underlying"] == "فملی"
    assert row["UnderlyingID"] == IID_A
    assert row["UnderlyingClose"] == 8000 and row["UnderlyingLast"] == 8050
    assert row["Strike"] == 9000 and row["DaysToExpiry"] == 44
    assert len(tse.derivatives.puts()) == 1


# ---------------------------------------------------------------- normalization
def test_text_normalization_and_ticker_key():
    assert normalize("كيان ۱۲۳") == "کیان 123"
    assert normalize("ملي‌ صنايع‌") == "ملی صنایع"           # ZWNJ before space / end removed
    assert normalize("می‌شود") == "می‌شود"                    # ZWNJ inside a word kept
    assert normalize(None) == "" and normalize(float("nan")) == ""
    assert ticker_key("بهين رو") == ticker_key("بهین‌رو") == ticker_key("بهینرو")
    assert ticker_key("فملي") == ticker_key("فملی") == ticker_key(" فـملی ")


def test_find_ignores_arabic_letters_and_spaces(tmp_path):
    arch = Archive(tmp_path / "a.sqlite", seed=False)
    rec = pd.DataFrame([["IR1", "فملي", "ملي مس", "", "1", "27", "100", "300"],
                        ["IR2", "بهين رو", "بهين", "", "1", "27", "100", "300"]],
                       columns=BASIC_COLUMNS, index=[IID_A, IID_B])
    arch.merge_instruments(rec)
    assert arch.instruments().loc[IID_A, "Ticker"] == "فملی"   # stored normalized
    assert list(arch.find("فملی").index) == [IID_A]
    assert list(arch.find("فملي").index) == [IID_A]
    assert list(arch.find("بهین‌رو").index) == [IID_B]


def test_contract_date_parsing():
    assert parse_persian_date("1405/08/11") == date(2026, 11, 2)
    asset, strike, expiry = _name_contract("اختيارخ خودرو-2,500-1405/09/25")
    assert (asset, strike, expiry) == ("خودرو", 2500, date(2026, 12, 16))
    assert _name_contract("unstructured") == (None, None, None)
    assert _name_contract("اختيارخ رو-100-1405/09/25")[0] == "بهین رو"


def test_jalali_roundtrip():
    for d in [date(2026, 11, 3), date(2025, 3, 20), date(2025, 3, 21), date(2024, 12, 31)]:
        assert jalali_to_gregorian(*gregorian_to_jalali(d)) == d
    assert gregorian_to_jalali(date(2026, 11, 3)) == (1405, 8, 12)


# ---------------------------------------------------------------- IDs
def test_ids_are_text_and_floats_rejected():
    assert coerce_id(65883838195688438) == LONG_ID      # Python int is exact
    assert coerce_id(" ۶۵۸۸۳۸۳۸۱۹۵۶۸۸۴۳۸ ") == LONG_ID   # Persian digits
    with pytest.raises(ValueError):
        coerce_id(6.5883838195688438e16)
    with pytest.raises(ValueError):
        coerce_id("6.588e+16")


def test_import_tda_rejects_numeric_id_cells(tmp_path):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "TDA"
    ws.append(["IndexURL", *BASIC_COLUMNS])
    ws.append([LONG_ID, "IR1", "الف", "الف", None, "1", "27", "100", "300"])
    ws.append([65883838195688438, "IR2", "ب", "ب", None, "1", "27", "100", "300"])  # numeric cell
    ws.append([123456789012345, "IR3", "پ", "پ", None, "1", "27", "100", "300.0"])   # 15 digits OK
    path = tmp_path / "tda.xlsx"; wb.save(path)
    arch = Archive(tmp_path / "a.sqlite", seed=False)
    with pytest.warns(UserWarning):
        result = arch.import_tda(path)
    assert result["added"] == 2 and len(result["rejected"]) == 1
    assert set(arch.instruments().index) == {LONG_ID, "123456789012345"}
    assert arch.instruments().loc["123456789012345", "Type"] == "300"


def test_export_tda_writes_text_cells(tmp_path):
    from openpyxl import load_workbook
    arch = Archive(tmp_path / "a.sqlite", seed=False)
    arch.merge_instruments(pd.DataFrame([["IR1", "x", "x", "", "1", "27", "100", "300"]],
                                        columns=BASIC_COLUMNS, index=[LONG_ID]))
    out = arch.export_tda(tmp_path / "out.xlsx")
    ws = load_workbook(out)["TDA"]
    assert ws.title == "TDA" and len(load_workbook(out).sheetnames) == 1
    cell = ws["A2"]
    assert cell.value == LONG_ID and isinstance(cell.value, str) and cell.number_format == "@"
    reread = Archive(tmp_path / "b.sqlite", seed=False)
    reread.import_tda(out)
    assert LONG_ID in reread.instruments().index


def test_to_excel_helper_keeps_ids(tmp_path):
    from openpyxl import load_workbook
    df = pd.DataFrame({"Close": [1.5]}, index=pd.Index([LONG_ID], name="IndexURL"))
    ws = load_workbook(to_excel(df, tmp_path / "x.xlsx")).active
    assert ws["A2"].value == LONG_ID and ws["B2"].value == 1.5


# ---------------------------------------------------------------- history / columns
def test_history_columns_close_is_final_price():
    raw = parse_history(DummyClient().daily_prices(IID_A), IID_A)
    assert list(raw.columns[:8]) == ["Date", "JDate", "Open", "High", "Low", "Close", "Last", "PrevClose"]
    assert raw.loc[0, "Close"] == 90 and raw.loc[0, "Last"] == 89   # Close=pClosing, Last=pDrCotVal
    assert raw.loc[0, "JDate"] == "1404/10/11"


def test_traded_only_is_user_choice():
    items = DummyClient().daily_prices(IID_A)
    assert len(parse_history(items, IID_A)) == 3                      # default keeps all days
    assert len(parse_history(items, IID_A, traded_only=True)) == 2


def test_price_adjustment_and_no_change_to_volume():
    client = DummyClient()
    raw = parse_history(client.daily_prices(IID_A), IID_A)
    adj = apply_adjustments(raw, parse_adjustments(client.price_adjustments(IID_A)))
    assert adj.loc[0, "AdjClose"] == 45 and adj.loc[0, "AdjLast"] == 44.5
    assert adj.loc[1, "AdjClose"] == 180
    assert adj.loc[0, "Volume"] == 100


# ---------------------------------------------------------------- archive
def test_archive_import_preserves_original_tda_and_merge(tmp_path):
    tse = M_TSE(tmp_path, client=DummyClient())
    assert tse.archive.count_instruments() == 6949
    before = tse.archive.instruments()
    rec = pd.DataFrame([["IR1", "نماد", "نام", "", "1", "42", "123", "311"]],
                       columns=BASIC_COLUMNS, index=pd.Index(["99999999999999999"], name="IndexURL"))
    assert tse.archive.merge_instruments(rec)["added"] == 1
    rec.loc["99999999999999999", "Ticker"] = None
    tse.archive.merge_instruments(rec)
    assert tse.archive.instruments().loc["99999999999999999", "Ticker"] == "نماد"
    assert before.index.isin(tse.archive.instruments().index).all()
    output = tse.archive.export_tda()
    from zipfile import ZipFile
    with ZipFile(output) as z:
        assert len([x for x in z.namelist() if x.startswith("xl/worksheets/sheet") and x.endswith(".xml")]) == 1


def test_bundled_tda_ids_and_types(tmp_path):
    tse = M_TSE(tmp_path)
    inst = tse.archive.instruments()
    assert inst.index.str.fullmatch(r"\d+").all()
    counts = inst["Type"].value_counts()
    assert "300.0" not in counts.index and "311.0" not in counts.index
    assert inst["Type"].isna().sum() == 1967
    assert not inst["Ticker"].dropna().str.contains("[يك]").any()   # normalized on import
    assert len(tse.archive.option_contracts()) > 1500
    assert len(tse.archive.instruments(types="Stock")) > 900


def test_update_tda_expired_ids_remain(sections, tmp_path):
    tse = M_TSE(tmp_path, client=DummyClient(sections), seed=False)
    assert tse.update_tda()["added"] == 3
    tse.client.sections = ["", "", make_line(IID_A, "خودرو", "300", "ایران خودرو"), ""]
    assert tse.update_tda()["total"] == 3
    assert IID_B in tse.archive.instruments().index


def test_sync_traded_only_default_and_override(sections, tmp_path):
    client = DummyClient(sections)
    tse = M_TSE(tmp_path, client=client, seed=False)
    tse.update_tda()
    out = tse.backfill(ids=[IID_A, IID_B], workers=2, refresh_adjustments=True)
    assert (out["status"] == "ok").all()
    assert tse.archive.count_prices() == 6                  # every day stored
    assert len(tse.archive.history(IID_A)) == 3
    assert len(tse.archive.history(IID_A, traded_only=True)) == 2
    tse.backfill(ids=[IID_A], workers=1, refresh_adjustments=True)
    assert tse.archive.count_prices() == 6                  # idempotent
    tse.backfill(ids=[IID_C], traded_only=True)
    assert len(tse.archive.history(IID_C)) == 2             # user chose traded days only
    picky = M_TSE(tmp_path / "p", client=client, seed=False, traded_only=True)
    picky.sync(IID_A)
    assert len(picky.stored_history(IID_A)) == 2
    assert len(picky.stored_history(IID_A, traded_only=False)) == 2
    assert tse.archive.coverage().loc[IID_A, "traded_days"] == 2


def test_sync_adjustment_failures_and_skip(sections, tmp_path):
    client = DummyClient(sections)
    tse = M_TSE(tmp_path, client=client, seed=False)
    tse.update_tda()
    tse.backfill(ids=[IID_A], refresh_adjustments=True)
    assert len(tse.archive.history(IID_A, start="2026-01-02")) == 2
    adjusted = tse.archive.history(IID_A, adjusted=True)
    assert adjusted.loc[0, "AdjHigh"] == 50 and adjusted.loc[1, "High"] == 200
    assert tse.archive.sync_one(IID_A, client, min_hours=12)["status"] == "skipped"
    client.fail.add(IID_C)
    report = tse.backfill(ids=[IID_C], workers=1)
    assert report.iloc[0]["status"] == "failed"
    assert tse.archive.count_prices() == 3
    assert tse.archive.stats()["failed"] == 1


def test_adjusted_requires_adjustment_cache(sections, tmp_path):
    tse = M_TSE(tmp_path, client=DummyClient(sections), seed=False)
    tse.archive.sync_one(IID_A, tse.client)
    with pytest.raises(DataSourceError):
        tse.archive.history(IID_A, adjusted=True)


def test_history_uses_unique_id_when_duplicate_ticker(tmp_path):
    tse = M_TSE(tmp_path, client=DummyClient(), seed=False)
    records = pd.DataFrame([
        ["IR1", "تکراری", "a", "", "1", "40", "42", "300"],
        ["IR2", "تكراري", "b", "", "1", "40", "42", "300"]],     # same ticker, Arabic letters
        columns=BASIC_COLUMNS, index=[IID_A, IID_B])
    tse.archive.merge_instruments(records)
    with pytest.raises(AmbiguousTicker):
        tse.history.resolve(ticker="تکراری")
    assert tse.history.resolve(instrument_id=IID_A) == IID_A
    with pytest.raises(ValueError):
        tse.history.resolve(instrument_id=1.1e16)


def test_empty_history_allowed(tmp_path):
    class EmptyClient:
        def daily_prices(self, iid, last=0):
            return []
    arch = Archive(tmp_path / "e.sqlite", seed=False)
    assert arch.sync_one(IID_A, EmptyClient())["status"] == "empty"
    assert arch.count_prices() == 0
    assert arch.history(IID_A).empty


def test_archive_option_contracts_and_backup(tmp_path):
    tse = M_TSE(tmp_path / "live", seed=False)
    records = pd.DataFrame([
        ["IR1", "ضخودA", "اختیارخ خودرو-2500-1405/09/25", "", "1", "40", "", "311"],
        ["IR2", "ضخودB", "اختیارف خودرو-3500-1405/10/20", "", "1", "40", "", "312"]],
        columns=BASIC_COLUMNS, index=[IID_A, IID_B])
    tse.archive.merge_instruments(records)
    calls = tse.archive.option_contracts(kind="call", today=date(2027, 1, 1))
    assert len(calls) == 1 and calls.iloc[0]["DaysToExpiry"] < 0
    target = tmp_path / "backup" / "safe.sqlite"
    tse.archive.backup(target)
    assert Archive(target, seed=False).count_instruments() == 2


def test_migration_from_tsemarketkit_v1(tmp_path):
    db = tmp_path / "tse_archive.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE instruments (instrument_id TEXT PRIMARY KEY, ircode TEXT, ticker TEXT, name TEXT,
      idk_1 TEXT, market_type TEXT, industry TEXT, stock_qty TEXT, type TEXT, first_seen TEXT, last_seen TEXT);
    CREATE TABLE prices (instrument_id TEXT NOT NULL, date TEXT NOT NULL, high REAL, low REAL,
      final REAL, close REAL, open REAL, yesterday REAL, value REAL, volume REAL, trades REAL,
      PRIMARY KEY (instrument_id, date));
    CREATE TABLE adjustments (instrument_id TEXT NOT NULL, date TEXT NOT NULL, factor REAL NOT NULL,
      PRIMARY KEY (instrument_id, date));
    CREATE TABLE synchronization (instrument_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL,
      outcome TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
      adjustments_at TEXT);
    """)
    con.execute("INSERT INTO instruments(instrument_id,ticker,name,type) VALUES(?,?,?,?)",
                (IID_A, "فملي", "ملي", "300"))
    con.execute("INSERT INTO prices VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (IID_A, "2026-01-01", 100, 80, 90, 89, 85, 88, 1000, 100, 2))
    con.commit(); con.close()
    arch = Archive(db, seed=False)
    assert arch.migration["from"] == 1 and Path(arch.migration["backup"]).exists()
    h = arch.history(IID_A)
    assert h.loc[0, "Close"] == 90 and h.loc[0, "Last"] == 89 and h.loc[0, "PrevClose"] == 88
    assert arch.find("فملی").index.tolist() == [IID_A]
    assert Archive(db, seed=False).migration is None       # runs only once


# ---------------------------------------------------------------- misc
def test_alias_and_cli_parser():
    assert TSEMarketKit is M_TSE
    from M_TSE.cli import build_parser
    args = build_parser().parse_args(["sync", "--all", "--traded-only"])
    assert args.traded_only and args.all


def test_client_new_api_with_injectable_session():
    from M_TSE.client import TSETMCClient
    class Response:
        def __init__(self, raw="", jsonval=None):
            self.text, self.jsonval = raw, jsonval
        def json(self): return self.jsonval
        def raise_for_status(self): return None
    seen = []
    class Session:
        def __init__(self): self.headers = {}
        def mount(self, *args): pass
        def get(self, url, timeout):
            seen.append(url)
            if "GetMarketWatch" in url: return Response(jsonval={"marketwatch": [new_row(IID_A, "x", "y")]})
            if "MarketWatchInit" in url: return Response("a@b@c@d")
            if "GetMarketOverview" in url: return Response(jsonval={"marketOverview": {}})
            if "GetInstrumentInfo" in url: return Response(jsonval={"instrumentInfo": {"yVal": "300"}})
            if "DailyList" in url: return Response(jsonval={"closingPriceDaily": []})
            return Response(jsonval={"priceAdjust": []})
    client = TSETMCClient(session_factory=Session)
    assert client.market_source == "new"
    assert len(client.market_watch()) == 1
    assert len(client.market_sections()) == 4
    assert client.instrument_info(IID_A)["yVal"] == "300"
    assert client.market_overview(2) == {}
    assert client.daily_prices(IID_A) == [] and client.price_adjustments(IID_A) == []
    assert any("cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch" in u for u in seen)
    assert 403 in client._retry.status_forcelist
    with pytest.raises(ValueError):
        TSETMCClient(market_source="bad")


def test_data_dir_prompt_and_memory(tmp_path, monkeypatch):
    import M_TSE as pkg
    monkeypatch.setattr(pkg, "CONFIG_FILE", tmp_path / "cfg" / "config.json")
    target = tmp_path / "my archive"
    monkeypatch.setattr("builtins.input", lambda prompt="": f'"{target}"')
    first = pkg.M_TSE(client=DummyClient(), seed=False)
    assert first.data_dir == target.resolve() and pkg.get_data_dir() == target.resolve()
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask twice"))
    assert pkg.M_TSE(client=DummyClient(), seed=False).data_dir == target.resolve()
    other = pkg.set_data_dir(tmp_path / "other")
    assert pkg.M_TSE(client=DummyClient(), seed=False).data_dir == other


def test_new_api_full_fields_nav_oi_board():
    opt = new_row(IID_B, "ضهرم8031", "اختيارخ شستا-100-1405/09/25")
    opt.update({"yVal": 311, "flow": 3, "buyOP": 288142, "pRedTran": 0.0, "cGrValCot": "3A", "yMarNSC": "NO"})
    fund = new_row(IID_C, "چتر", "صندوق")
    fund.update({"yVal": 305, "flow": 2, "buyOP": 0, "pRedTran": 23674.0, "cGrValCot": "T1", "yMarNSC": "NO"})
    stock = new_row(IID_A, "وسپهر", "سپهر")
    stock.update({"yVal": 303, "flow": 2, "buyOP": 0, "pRedTran": 0.0, "cGrValCot": "Z1", "yMarNSC": "NO"})
    b = parse_market_watch([opt, fund, stock])
    assert b.loc[IID_B, "Type"] == "311" and b.loc[IID_B, "MarketType"] == "3"
    assert b.loc[IID_B, "OpenInterest"] == 288142 and b.loc[IID_B, "Board"] == "3A"
    assert b.loc[IID_C, "Nav"] == 23674 and pd.isna(b.loc[IID_C, "OpenInterest"])
    assert pd.isna(b.loc[IID_A, "Nav"]) and pd.isna(b.loc[IID_A, "OpenInterest"])
    assert b.loc[IID_A, "MarketCode"] == "NO"


def test_legacy_25_values_board(sections):
    f = make_line(IID_B, "ضهرم8024", "311", "اختيارخ شستا-100-1405/09/25").split(",")
    f.extend(["", "6910", "3A"])
    sections[2] = ",".join(f)
    b = parse_watch(sections)
    assert b.loc[IID_B, "OpenInterest"] == 6910 and b.loc[IID_B, "Board"] == "3A"
    assert pd.isna(b.loc[IID_B, "Nav"])


def test_stream_yields_only_changes(new_rows, tmp_path):
    client = DummyClient(rows=[dict(r) for r in new_rows])
    tse = M_TSE(tmp_path, client=client, seed=False, enrich=False)
    gen = tse.market.stream(interval=0, duration=5)
    _, first = next(gen)
    assert len(first) == 3
    _, second = next(gen)
    assert second.empty
    client.rows[0] = dict(client.rows[0], pdv=8100.0)
    _, third = next(gen)
    assert list(third.index) == [IID_A] and third.loc[IID_A, "Last"] == 8100
