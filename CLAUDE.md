# M_TSE — context for Claude Code

Owner: AHM-Mohammadi (Persian speaker; reply in Persian, code/identifiers English). Public repo.
Python library for TSETMC (Tehran Stock Exchange) market data + durable SQLite archive.
Used by the private project **M_Options** (option watch list) as a dependency — don't break its API.

## Status (v1.3.2)
- Verified LIVE by the user: new-API snapshot, NAV, open interest, board code, stream.
- User env: Windows 10, Anaconda base `C:\Users\a.mohammadi\AppData\Local\anaconda3\python.exe`,
  archive folder `C:\Users\a.mohammadi\Documents\Archive Updater\M_TSE` (saved in ~/.m_tse/config.json).
- Install/upgrade: `pip install --upgrade git+https://github.com/AHM-Mohammadi/M_TSE.git`

## Layout (src/M_TSE)
- `client.py`  TSETMCClient: new API (cdn.tsetmc.com/api) default; market_source new|old|auto; retries incl. 403;
  shared min_interval throttle. Endpoints: ClosingPrice/GetMarketWatch, MarketData/GetMarketOverview/{1,2},
  Instrument/GetInstrumentInfo/{id}, ClosingPrice/GetClosingPriceDailyList/{id}/0, ClosingPrice/GetPriceAdjustList/{id}.
- `market.py`  parse_market_watch (new JSON, 42 keys/row), parse_watch/parse_depth (old, 22 or 25 values),
  Market.snapshot/overview/by_type/stream, filter_type, TYPE_CODES.
- `derivatives.py` options/calls/puts/futures; contract specs parsed from NAME (underlying-strike-jalali date).
  Underlying = longest word-suffix of the name head that matches a board ticker (resolve_underlying, 1.3.1; e.g.
  «جوانه کوچک»), then dotted abbreviations (match_abbreviation, 1.3.2: «جوانه.ک»), else last word + UNDERLYING_ALIASES.
- `history.py`  fetch/fetch_many, parse_history, adjustments (factor = pClosing/pClosingNotAdjusted, applied to days
  strictly before event).
- `archive.py`  SQLite (schema v2, PRAGMA user_version; auto-migrates v1 with .v1-backup copy), TDA Excel export
  with TEXT id cells, sync_one/sync_many/backfill, history, coverage.
- `utils.py`  normalize (ی/ک, digits, ZWNJ), ticker_key, coerce_id (rejects floats), to_excel, jalali helpers.
- `__init__.py` class M_TSE (alias TSEMarketKit), set_data_dir/get_data_dir (first-run prompt).
- CLI `mtse` / `python -m M_TSE`.

## Hard rules / decisions
- Instrument IDs are ALWAYS text (14–19 digits; floats/Excel lose digits).
- Column convention everywhere: `Close = pClosing` (final, weighted price), `Last = pDrCotVal`, `PrevClose`, `Trades`.
- New API field map: yVal→Type, flow→MarketType, buyOP→OpenInterest (only derivatives, else NaN),
  pRedTran→Nav (only >0), cGrValCot→Board, yMarNSC→MarketCode, pcl→Close, pdv→Last.
- `traded_only` is user's choice; default keeps all days (stored too).
- Untraded options have Close=1 from TSETMC — user chose to keep as is.
- Text: store normalized Persian; match with ticker_key.
- Tests: `python -m pytest -q` (34 tests). Update docs/*_FA.md + CHANGELOG.md (Persian), bump version in
  pyproject.toml and src/M_TSE/__init__.py.

## Pending ideas
- Option specs (strike, expiry, contract size, underlying) from a TSETMC API instead of name parsing.
- Client-type (حقیقی/حقوقی), index history, fund NAV history.
