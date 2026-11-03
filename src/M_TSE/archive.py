"""Permanent SQLite histories + legacy-compatible single-sheet TDA export."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
import importlib.resources
import os
import sqlite3
import tempfile
import threading
import warnings
import pandas as pd

from .history import (HISTORY_COLUMNS, VALUE_COLUMNS, add_jalali, apply_adjustments,
                      filter_traded, parse_history, parse_adjustments)
from .market import BASIC_COLUMNS, _code_text
from .utils import coerce_id, is_valid_id, iso_date, normalize_or_none, ticker_key, to_excel
from .errors import DataSourceError

SCHEMA_VERSION = 2

# SQLite is the permanent price store. Excel is only the TDA identifier directory.
CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS instruments (
  instrument_id TEXT PRIMARY KEY, ircode TEXT, ticker TEXT, name TEXT,
  idk_1 TEXT, market_type TEXT, industry TEXT, stock_qty TEXT, type TEXT,
  first_seen TEXT, last_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickers ON instruments(ticker);
CREATE INDEX IF NOT EXISTS idx_types ON instruments(type);
CREATE TABLE IF NOT EXISTS prices (
  instrument_id TEXT NOT NULL, date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, last REAL, prev_close REAL,
  volume REAL, value REAL, trades REAL,
  PRIMARY KEY (instrument_id, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);
CREATE TABLE IF NOT EXISTS adjustments (
  instrument_id TEXT NOT NULL, date TEXT NOT NULL, factor REAL NOT NULL,
  PRIMARY KEY (instrument_id, date)
);
CREATE TABLE IF NOT EXISTS synchronization (
  instrument_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL,
  outcome TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '', adjustments_at TEXT
);
"""
META_TO_SQL = {"IRcode": "ircode", "Ticker": "ticker", "Name": "name", "IDK_1": "idk_1",
               "MarketType": "market_type", "Industry": "industry", "StockQty": "stock_qty",
               "Type": "type"}
PRICE_TO_SQL = {"Open": "open", "High": "high", "Low": "low", "Close": "close",
                "Last": "last", "PrevClose": "prev_close", "Volume": "volume",
                "Value": "value", "Trades": "trades"}
_CODE_FIELDS = {"IRcode", "MarketType", "Industry", "StockQty", "Type", "IDK_1"}


def _value(field, x):
    if field in ("Ticker", "Name"):
        return normalize_or_none(x)
    return _code_text(x)


def _number(x):
    return None if pd.isna(x) else float(x)


class Archive:
    def __init__(self, db_path="tse_archive.sqlite", tda_path=None, *, seed=True):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.tda_path = Path(tda_path).expanduser().resolve() if tda_path else None
        self._write_lock = threading.Lock()   # one writer at a time (worker threads)
        self.migration = self._migrate()
        if self.count_instruments() == 0 and seed:
            self.import_tda(self.tda_path if self.tda_path and self.tda_path.exists() else None)

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(str(self.db_path), timeout=60)
        try:
            con.execute("PRAGMA busy_timeout=60000")
            con.execute("PRAGMA journal_mode=WAL")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @contextmanager
    def _writer(self):
        with self._write_lock, self._connect() as con:
            yield con

    # ------------------------------------------------------------ schema
    def _migrate(self):
        """Create tables or upgrade a TSEMarketKit 1.0 database in place.

        v1 -> v2: price columns renamed so that ``close`` = pClosing (final
        price) and ``last`` = pDrCotVal; ticker/name normalized to Persian ی/ک.
        A copy of the v1 file is kept next to it before any change.
        """
        existed = self.db_path.exists() and self.db_path.stat().st_size > 0
        with self._connect() as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            cols = {r[1] for r in con.execute("PRAGMA table_info(prices)")}
        if version >= SCHEMA_VERSION:
            return None
        if existed and "final" in cols:
            backup = self.db_path.with_name(self.db_path.stem + ".v1-backup" + self.db_path.suffix)
            if not backup.exists():
                self.backup(backup)
            with self._writer() as con:
                con.execute("""CREATE TABLE prices_v2 (
                  instrument_id TEXT NOT NULL, date TEXT NOT NULL,
                  open REAL, high REAL, low REAL, close REAL, last REAL, prev_close REAL,
                  volume REAL, value REAL, trades REAL, PRIMARY KEY (instrument_id, date))""")
                con.execute("""INSERT INTO prices_v2 SELECT instrument_id, date, open, high, low,
                  final, close, yesterday, volume, value, trades FROM prices""")
                con.execute("DROP TABLE prices")
                con.execute("ALTER TABLE prices_v2 RENAME TO prices")
                con.execute("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date)")
                rows = con.execute("SELECT instrument_id, ticker, name FROM instruments").fetchall()
                con.executemany("UPDATE instruments SET ticker=?, name=? WHERE instrument_id=?",
                                [(normalize_or_none(t), normalize_or_none(n), i) for i, t, n in rows])
                con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            result = {"from": 1, "to": SCHEMA_VERSION, "backup": str(backup)}
        else:
            result = None
        with self._writer() as con:
            con.executescript(CREATE_TABLES)
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        return result

    # ------------------------------------------------------------ counts
    def count_instruments(self):
        with self._connect() as con:
            return con.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]

    def count_prices(self):
        with self._connect() as con:
            return con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]

    # ------------------------------------------------------------ TDA directory
    @staticmethod
    def _read_tda_sheet(path):
        """Read the TDA sheet cell-by-cell so numeric (corrupted) IDs are detected."""
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            if "TDA" not in wb.sheetnames:
                raise ValueError(f"No 'TDA' sheet in {path}")
            rows = wb["TDA"].iter_rows(values_only=True)
            header = [str(h).strip() if h is not None else "" for h in next(rows)]
            records, index, rejected = [], [], []
            for line, row in enumerate(rows, start=2):
                if not row or row[0] is None:
                    continue
                raw = row[0]
                if isinstance(raw, float) or (isinstance(raw, int) and len(str(raw)) > 15):
                    # Stored by Excel as a number: digits beyond 15 are unreliable.
                    rejected.append({"row": line, "value": repr(raw),
                                     "reason": "numeric cell; ID digits may be corrupted"})
                    continue
                if not is_valid_id(raw):
                    rejected.append({"row": line, "value": repr(raw), "reason": "not a digit ID"})
                    continue
                index.append(coerce_id(raw))
                records.append(dict(zip(header[1:], row[1:])))
        finally:
            wb.close()
        frame = pd.DataFrame(records, index=pd.Index(index, name="IndexURL"), dtype="object")
        return frame.reindex(columns=BASIC_COLUMNS), rejected

    def import_tda(self, path=None):
        """Import a TDA .xlsx (or the bundled one); merge, *never delete* old IDs."""
        if path is None:
            ref = importlib.resources.files("M_TSE").joinpath("data", "Ticker Data Archive.xlsx")
            with importlib.resources.as_file(ref) as bundled:
                data, rejected = self._read_tda_sheet(bundled)
        else:
            data, rejected = self._read_tda_sheet(path)
        if rejected:
            warnings.warn(f"{len(rejected)} TDA rows skipped: ID stored as a number or invalid "
                          f"(first: {rejected[0]}). Store IDs as text cells.", stacklevel=2)
        result = self.merge_instruments(data, source="import") if not data.empty else \
            {"received": 0, "added": 0, "total": self.count_instruments()}
        result["rejected"] = rejected
        return result

    def merge_instruments(self, dataframe, *, source="online"):
        """Merge by instrument ID; never delete, never overwrite a known value with blank."""
        if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
            raise ValueError("No instrument data: archive unchanged")
        missing = [col for col in BASIC_COLUMNS if col not in dataframe.columns]
        if missing:
            raise ValueError(f"Missing instrument fields: {missing}")
        valid = dataframe.loc[[is_valid_id(i) and not isinstance(i, float) for i in dataframe.index]]
        valid = valid.copy()
        valid.index = [coerce_id(i) for i in valid.index]
        valid = valid.loc[~valid.index.duplicated(keep="last")]
        if valid.empty:
            raise ValueError("No valid IndexURL: archive unchanged")
        timestamp = datetime.now(timezone.utc).isoformat()
        columns = ["instrument_id", *META_TO_SQL.values(), "first_seen", "last_seen"]
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{col}=COALESCE(excluded.{col}, instruments.{col})"
                           for col in META_TO_SQL.values())
        if source == "online":
            updates += ",last_seen=excluded.last_seen"
        sql = (f"INSERT INTO instruments ({','.join(columns)}) VALUES({placeholders}) "
               f"ON CONFLICT(instrument_id) DO UPDATE SET {updates}")
        rows = []
        for iid, record in zip(valid.index, valid.to_dict("records")):
            meta = [_value(col, record.get(col)) for col in META_TO_SQL]
            rows.append((iid, *meta, timestamp, timestamp if source == "online" else None))
        with self._writer() as con:
            before = con.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
            con.executemany(sql, rows)
            total = con.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
        return {"received": len(rows), "added": total - before, "total": total}

    def instruments(self, *, types=None):
        sql = ("SELECT instrument_id, ircode, ticker, name, idk_1, market_type, industry, "
               "stock_qty, type FROM instruments")
        with self._connect() as con:
            df = pd.read_sql_query(sql, con, dtype="object")
        df.columns = ["IndexURL", *META_TO_SQL.keys()]
        df = df.set_index("IndexURL")
        df.index = df.index.astype(str)
        if types is not None:
            from .market import filter_type
            df = filter_type(df, types)
        return df

    def find(self, ticker):
        """All IDs whose ticker matches, ignoring ی/ي, ک/ك, spaces and half-spaces."""
        key = ticker_key(ticker)
        frame = self.instruments()
        return frame.loc[frame["Ticker"].map(ticker_key) == key]

    def option_contracts(self, *, kind="both", today=None):
        """Offline registry of all known options, including expired ones."""
        from .derivatives import add_contract_columns
        if kind not in ("both", "call", "put"):
            raise ValueError("kind must be call, put or both")
        types = {"both": ["CallOption", "PutOption"],
                 "call": ["CallOption"], "put": ["PutOption"]}[kind]
        return add_contract_columns(self.instruments(types=types), today=today)

    def backup(self, destination):
        """Create consistent SQLite backup, safe while source uses WAL."""
        destination = Path(destination).expanduser().resolve()
        if destination == self.db_path:
            raise ValueError("Backup target must differ from active SQLite database")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
                target.commit()
            finally:
                target.close()
        return destination

    def export_tda(self, path=None):
        """Atomic TDA-only .xlsx export; IDs and codes are written as *text* cells."""
        destination = Path(path or self.tda_path or "Ticker Data Archive.xlsx").expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".tda_", suffix=".xlsx",
                                         delete=False) as tmp:
            temp = Path(tmp.name)
        try:
            to_excel(self.instruments(), temp, sheet_name="TDA", index=True)
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        return destination

    def update_tda(self, market, *, export=True):
        current = market.snapshot(numeric=False)
        result = self.merge_instruments(current, source="online")
        result["source"] = getattr(market, "last_source", None)
        if export:
            self.export_tda()
        return result

    # ------------------------------------------------------------ prices
    def _save_prices(self, iid, prices):
        args = [(iid, rec["Date"].date().isoformat(), *(_number(rec[k]) for k in PRICE_TO_SQL))
                for rec in prices.to_dict("records")]
        if args:
            with self._writer() as con:
                con.executemany(f"""INSERT INTO prices (instrument_id,date,{','.join(PRICE_TO_SQL.values())})
                VALUES ({','.join('?' * (len(PRICE_TO_SQL) + 2))})
                ON CONFLICT(instrument_id,date) DO UPDATE SET
                {','.join(f'{c}=excluded.{c}' for c in PRICE_TO_SQL.values())}""", args)
        return len(args)

    def _save_adjustments(self, iid, events):
        now = datetime.now(timezone.utc).isoformat()
        with self._writer() as con:
            # A complete response replaces only the cached adjustments of this ID.
            con.execute("DELETE FROM adjustments WHERE instrument_id=?", (iid,))
            con.executemany("INSERT INTO adjustments VALUES(?,?,?)", [
                (iid, row["Date"].date().isoformat(), float(row["Factor"]))
                for row in events.to_dict("records")])
            con.execute("""INSERT INTO synchronization(instrument_id,checked_at,outcome,row_count,message,adjustments_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET adjustments_at=excluded.adjustments_at""",
                (iid, now, "adjustments_only", 0, "", now))

    def _checked(self, iid, outcome, row_count=0, message=""):
        with self._writer() as con:
            con.execute("""INSERT INTO synchronization(instrument_id,checked_at,outcome,row_count,message)
                VALUES(?,?,?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET
                checked_at=excluded.checked_at,outcome=excluded.outcome,
                row_count=excluded.row_count,message=excluded.message""",
                (iid, datetime.now(timezone.utc).isoformat(), outcome, int(row_count), str(message)[:1000]))

    def last_sync(self, iid):
        with self._connect() as con:
            return con.execute("SELECT checked_at,outcome,adjustments_at FROM synchronization "
                               "WHERE instrument_id=?", (iid,)).fetchone()

    def sync_one(self, iid, client, *, refresh_adjustments=False, min_hours=0, last=0,
                 traded_only=False):
        """Fetch by unique ID and upsert daily prices; optionally cache adjustments.

        ``traded_only=False`` (default) stores every day the server returns,
        including days without trades, so nothing is lost; filter on read.
        Existing rows are never deleted.
        """
        iid = coerce_id(iid)
        old = self.last_sync(iid)
        if old and float(min_hours) > 0 and old[1] in ("ok", "empty"):
            last_checked = datetime.fromisoformat(old[0])
            if datetime.now(timezone.utc) - last_checked < timedelta(hours=float(min_hours)):
                if not refresh_adjustments or old[2] is not None:
                    return {"id": iid, "status": "skipped", "rows": 0}
        try:
            frame = parse_history(client.daily_prices(iid, last=last), iid,
                                  traded_only=bool(traded_only))
            events = parse_adjustments(client.price_adjustments(iid)) if refresh_adjustments else None
            inserted = self._save_prices(iid, frame)
            if refresh_adjustments:
                self._save_adjustments(iid, events)
            status = "ok" if inserted else "empty"
            self._checked(iid, status, inserted)
            return {"id": iid, "status": status, "rows": inserted}
        except Exception as exc:
            self._checked(iid, "failed", 0, str(exc))
            return {"id": iid, "status": "failed", "rows": 0, "error": str(exc)}

    def sync_many(self, client, *, ids=None, types=None, workers=4, min_hours=0,
                  refresh_adjustments=False, progress=None, last=0, traded_only=False):
        """Resume-safe archive sync. Includes historical/expired IDs from TDA."""
        if ids is None:
            ids = self.instruments(types=types).index.tolist()
        ids = list(dict.fromkeys(coerce_id(x) for x in ids))
        if not ids:
            return pd.DataFrame(columns=["id", "status", "rows", "error"])
        results = {}
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            future_map = {pool.submit(self.sync_one, iid, client,
                                      refresh_adjustments=refresh_adjustments, min_hours=min_hours,
                                      last=last, traded_only=traded_only): iid for iid in ids}
            for i, future in enumerate(as_completed(future_map), 1):
                iid = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"id": iid, "status": "failed", "rows": 0, "error": str(exc)}
                results[iid] = result
                if progress is not None:
                    progress(i, len(ids), result)
        return pd.DataFrame([results[i] for i in ids])

    def history(self, instrument_id, *, adjusted=False, start=None, end=None, traded_only=False):
        """Offline history from SQLite. ``traded_only=True`` hides days without trades."""
        iid = coerce_id(instrument_id)
        with self._connect() as con:
            query = ("SELECT date," + ",".join(PRICE_TO_SQL.values()) +
                     " FROM prices WHERE instrument_id=?")
            args = [iid]
            if start is not None:
                query += " AND date>=?"; args.append(iso_date(start))
            if end is not None:
                query += " AND date<=?"; args.append(iso_date(end))
            query += " ORDER BY date"
            frame = pd.read_sql_query(query, con, params=args)
            meta = con.execute("SELECT adjustments_at FROM synchronization WHERE instrument_id=?",
                               (iid,)).fetchone()
            events = pd.read_sql_query(
                "SELECT date AS Date, factor AS Factor FROM adjustments WHERE instrument_id=? ORDER BY date",
                con, params=[iid]) if adjusted else None
        frame.columns = ["Date", *PRICE_TO_SQL.keys()]
        frame["Date"] = pd.to_datetime(frame["Date"])
        for col in VALUE_COLUMNS:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float64")
        frame["IndexURL"] = iid
        add_jalali(frame)
        frame = filter_traded(frame[HISTORY_COLUMNS], traded_only)
        if adjusted:
            if meta is None or meta[0] is None:
                raise DataSourceError(f"No cached adjustment data for {iid}: "
                                      "run sync_one(..., refresh_adjustments=True)")
            events["Date"] = pd.to_datetime(events["Date"])
            frame = apply_adjustments(frame, events)
        return frame

    def coverage(self, ids=None):
        """First/last stored date and row counts per ID (check archive completeness)."""
        with self._connect() as con:
            frame = pd.read_sql_query(
                "SELECT instrument_id AS IndexURL, MIN(date) AS first_date, MAX(date) AS last_date, "
                "COUNT(*) AS rows, SUM(CASE WHEN trades>0 THEN 1 ELSE 0 END) AS traded_days "
                "FROM prices GROUP BY instrument_id", con, dtype={"IndexURL": "object"})
        frame = frame.set_index("IndexURL")
        if ids is not None:
            frame = frame.loc[frame.index.isin([coerce_id(i) for i in ids])]
        return frame

    def sync_report(self):
        with self._connect() as con:
            return pd.read_sql_query(
                "SELECT instrument_id AS IndexURL, checked_at, outcome, row_count, message, adjustments_at "
                "FROM synchronization ORDER BY checked_at DESC", con, dtype={"IndexURL": "object"})

    def stats(self):
        with self._connect() as con:
            groups = dict(con.execute("SELECT outcome, COUNT(*) FROM synchronization GROUP BY outcome").fetchall())
        return {"instruments": self.count_instruments(), "price_rows": self.count_prices(),
                "synced_ok": groups.get("ok", 0), "empty": groups.get("empty", 0),
                "failed": groups.get("failed", 0)}
