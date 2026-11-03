"""Command line entrypoint: ``mtse --help`` (or ``python -m M_TSE --help``)."""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
import sys

from . import M_TSE
from .errors import TSEMarketError
from .utils import to_excel


def _save(data, path, *, index):
    """.xlsx -> text-safe IDs; anything else -> UTF-8 CSV."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        to_excel(data, path, index=index)
    else:
        data.to_csv(path, index=index, encoding="utf-8-sig")
    print(f"Saved {len(data)} rows to {path}")


def build_parser():
    p = argparse.ArgumentParser(prog="mtse", description="M_TSE: TSETMC market data + SQLite history archive")
    p.add_argument("--data-dir", default=None, help="Archive folder (default: saved folder; asked on first run)")
    p.add_argument("--source", choices=["new", "old", "auto"], default="new",
                   help="Market-watch source: new cdn.tsetmc.com API (default), old site, or auto")
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("init", help="Initialize archive from bundled TDA")
    setdir = actions.add_parser("set-dir", help="Remember the archive folder for later runs")
    setdir.add_argument("path")
    actions.add_parser("status", help="Show archive statistics")
    actions.add_parser("update-tda", help="Fetch market-watch and retain all historic IDs")
    actions.add_parser("export-tda", help="Export ONLY the TDA Excel sheet")
    backup = actions.add_parser("backup", help="Consistent SQLite archive backup")
    backup.add_argument("--output", required=True)
    watch = actions.add_parser("watch", help="Current market-watch snapshot")
    watch.add_argument("--type", action="append", dest="types", help="Class name or type code; repeatable")
    watch.add_argument("--depth", action="store_true", help="Include five order-book levels")
    watch.add_argument("--limit", type=int, default=20)
    watch.add_argument("--csv", "--out", dest="out", help="Output file (.csv or .xlsx)")
    options = actions.add_parser("options", help="Current option contracts with strikes/expiry")
    options.add_argument("--kind", choices=["both", "call", "put"], default="both")
    options.add_argument("--no-depth", action="store_true")
    options.add_argument("--csv", "--out", dest="out", help="Output file (.csv or .xlsx)")
    sync = actions.add_parser("sync", help="Download/upsert daily prices by historical ID")
    which = sync.add_mutually_exclusive_group(required=True)
    which.add_argument("--all", action="store_true", help="All known IDs, including expired contracts")
    which.add_argument("--id", action="append", dest="ids", help="Selected IndexURL (repeatable)")
    sync.add_argument("--type", action="append", dest="types", help="Restrict --all to types")
    sync.add_argument("--workers", type=int, default=3)
    sync.add_argument("--min-hours", type=float, default=0, help="Skip recently successful IDs")
    sync.add_argument("--with-adjustments", action="store_true", help="Also cache adjustment events")
    sync.add_argument("--traded-only", action="store_true",
                      help="Do NOT store days without trades (default: store every day)")
    sync.add_argument("--report", help="Save per-ID sync result as CSV")
    history = actions.add_parser("history", help="Read cached or live historical prices")
    hwhich = history.add_mutually_exclusive_group(required=True)
    hwhich.add_argument("--ticker")
    hwhich.add_argument("--id", dest="id")
    history.add_argument("--online", action="store_true", help="Fetch from TSETMC instead of SQLite")
    history.add_argument("--adjusted", action="store_true")
    history.add_argument("--traded-only", action="store_true", help="Hide days without trades")
    history.add_argument("--start", help="ISO Gregorian date YYYY-MM-DD (cached only)")
    history.add_argument("--end", help="ISO Gregorian date YYYY-MM-DD (cached only)")
    history.add_argument("--csv", "--out", dest="out", help="Output file (.csv or .xlsx)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if hasattr(args, "workers") and not 1 <= args.workers <= 12:
        raise SystemExit("--workers must be between 1 and 12")
    if args.action == "set-dir":
        from . import set_data_dir
        print(f"Archive folder saved: {set_data_dir(args.path)}")
        return 0
    tse = M_TSE(data_dir=args.data_dir, market_source=args.source)
    if tse.archive.migration:
        print(f"Archive upgraded to schema v2; previous file kept at {tse.archive.migration['backup']}")
    try:
        if args.action == "init":
            output = tse.archive.export_tda()
            print(f"Initialized: {tse.archive.stats()} | TDA: {output}")
        elif args.action == "status":
            print(tse.archive.stats())
        elif args.action == "update-tda":
            print(tse.update_tda())
        elif args.action == "export-tda":
            print(tse.archive.export_tda())
        elif args.action == "backup":
            print(tse.archive.backup(args.output))
        elif args.action == "watch":
            data = (tse.market.by_type(args.types, depth=args.depth) if args.types
                    else tse.market.snapshot(depth=args.depth))
            if args.out:
                _save(data, args.out, index=True)
            else:
                print(data.head(args.limit).to_string())
                print(f"Total: {len(data)} instruments (source: {tse.market.last_source})")
        elif args.action == "options":
            data = tse.derivatives.options(kind=args.kind, depth=not args.no_depth)
            if args.out:
                _save(data, args.out, index=True)
            else:
                cols = [c for c in ["Ticker", "OptionKind", "Underlying", "Strike", "Expiry",
                                    "DaysToExpiry", "Close", "Last", "Volume"] if c in data]
                print(data[cols].head(30).to_string())
                print(f"Total: {len(data)} contracts")
        elif args.action == "sync":
            def progress(i, n, result):
                if i == 1 or i % 50 == 0 or i == n or result["status"] == "failed":
                    print(f"{i}/{n}: {result['id']} {result['status']} ({result.get('rows', 0)} rows)", flush=True)
            output = tse.backfill(ids=args.ids, types=args.types, workers=args.workers,
                                  min_hours=args.min_hours, refresh_adjustments=args.with_adjustments,
                                  progress=progress, traded_only=args.traded_only)
            report_file = (Path(args.report) if args.report else
                           tse.data_dir / ("sync_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"))
            report_file.parent.mkdir(parents=True, exist_ok=True)
            output.to_csv(report_file, index=False, encoding="utf-8-sig")
            print(f"Saved sync report: {report_file}")
            print(output["status"].value_counts(dropna=False).to_string() if len(output) else "No IDs")
            if "failed" in output["status"].values:
                return 2
        elif args.action == "history":
            iid = tse.history.resolve(ticker=args.ticker, instrument_id=args.id)
            if args.online:
                data = tse.history.fetch(instrument_id=iid, adjusted=args.adjusted,
                                         traded_only=args.traded_only)
            else:
                data = tse.archive.history(iid, adjusted=args.adjusted, start=args.start,
                                           end=args.end, traded_only=args.traded_only)
            if args.out:
                _save(data, args.out, index=False)
            else:
                print(data.tail(20).to_string(index=False))
                print(f"Total rows: {len(data)}")
    except (OSError, ValueError, RuntimeError, KeyError, TSEMarketError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
