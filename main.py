"""
main.py — CLI entrypoint

Commands:
  python main.py opt-vol           run today's report (brief output + Excel)
  python main.py opt-vol --full    also print full signal detail
  python main.py opt-vol --date 2026-05-27   run for a specific date
  python main.py opt-vol --debug   verbose logging
"""
import argparse
import logging
import sys
from datetime import date


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        format  = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt = "%H:%M:%S",
        level   = level,
    )


def cmd_opt_vol(args) -> None:
    from signals.pipeline import OptionsVolumePipeline

    trade_date = None
    if args.date:
        try:
            trade_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
            sys.exit(1)

    pipeline = OptionsVolumePipeline()
    result   = pipeline.run(trade_date=trade_date)

    if args.full:
        print(result.summary())


def main():
    parser = argparse.ArgumentParser(
        description="flow-lens — options flow signal engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py opt-vol
  python main.py opt-vol --date 2026-05-27
  python main.py opt-vol --full
  python main.py opt-vol --debug
        """
    )
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="command")

    vol = sub.add_parser("opt-vol", help="run options volume leaders report")
    vol.add_argument("--full",  action="store_true", help="also print full signal detail (brief table is always shown)")
    vol.add_argument("--date",  type=str, default=None, metavar="YYYY-MM-DD",
                     help="run for a specific date (default: today)")

    args = parser.parse_args()
    setup_logging(args.debug)

    if args.command == "opt-vol":
        cmd_opt_vol(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
