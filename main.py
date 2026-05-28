"""
main.py — CLI entrypoint  (replaces Program.cs command dispatch)

Usage:
    python main.py opt-vol          # run Options Volume Leaders report
    python main.py opt-vol --debug  # verbose logging
"""
import argparse
import logging
import sys


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        format  = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt = "%H:%M:%S",
        level   = level,
    )


def cmd_opt_vol(args) -> None:
    from signals.pipeline import OptionsVolumePipeline
    pipeline = OptionsVolumePipeline()
    pipeline.run()


def main():
    parser = argparse.ArgumentParser(
        description = "ShareRatings — Options signal generator"
    )
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("opt-vol", help="Run Options Volume Leaders report")

    args = parser.parse_args()
    setup_logging(args.debug)

    if args.command == "opt-vol":
        cmd_opt_vol(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
