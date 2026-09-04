"""Shared CLI helpers for output directory resolution."""

from __future__ import annotations

import argparse

from github_analysis.config import OUTPUT_DIR_HELP, resolve_output_dir


def add_output_dir_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help=OUTPUT_DIR_HELP,
    )


def apply_output_dir(args: argparse.Namespace) -> None:
    """Set args.output_dir using CLI → env → default precedence."""
    args.output_dir = resolve_output_dir(getattr(args, "output_dir", None))
