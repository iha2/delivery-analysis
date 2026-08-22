# Instructions for AI assistants

## CLI structure

Single entry point: `github-analysis` (via `uv run github-analysis`).

| Command | Module |
|---------|--------|
| `analyze` | `github_analysis/cli/commands/analyze.py` |
| `export` | `github_analysis/cli/commands/export.py` |
| `run` | `github_analysis/cli/commands/run.py` |

To add a command: see [docs/extending-the-cli.md](docs/extending-the-cli.md).

## Package layout

See [docs/architecture.md](docs/architecture.md) for module map, pipeline phases, and catalog search conventions.

Update `README.md` when CLI surface or output columns change.

## Corpus index

Code exploration follows the **Index Protocol** (`.agents/skills/graphify-search/SKILL.md`): subgraph retrieval before lexical search.
