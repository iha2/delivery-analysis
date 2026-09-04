"""CLI command handlers."""

from github_analysis.cli.commands.analyze import register as register_analyze
from github_analysis.cli.commands.export import register as register_export
from github_analysis.cli.commands.run import register as register_run

COMMAND_REGISTRARS = [
    register_analyze,
    register_export,
    register_run,
]

__all__ = ["COMMAND_REGISTRARS"]
