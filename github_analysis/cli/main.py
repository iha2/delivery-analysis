"""Compatibility entry point: the command line now lives in delivery_analysis.cli.main."""

from delivery_analysis.cli.main import build_parser, main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
