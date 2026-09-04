# Extending the CLI

## Adding a command

1. Create `github_analysis/cli/commands/mycommand.py` with:
   - `register(subparsers)` — define flags and `parser.set_defaults(handler=run)`
   - `run(args) -> int` — command logic
2. Register in `github_analysis/cli/commands/__init__.py` → `COMMAND_REGISTRARS`

The command appears in `github-analysis --help` and gets its own `--help`.

## Existing commands

| Command | Module |
|---------|--------|
| `analyze` | `github_analysis/cli/commands/analyze.py` |
| `export` | `github_analysis/cli/commands/export.py` |
| `run` | `github_analysis/cli/commands/run.py` |

## Documentation

Update `README.md` when CLI flags or output columns change.
