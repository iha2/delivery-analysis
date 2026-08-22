#!/bin/bash
set -euo pipefail

# Consume hook JSON input to avoid broken pipes from Cursor.
INPUT_JSON=$(cat || true)

# Run from repository root so relative graphify paths resolve.
REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO_ROOT"

# Prefer a resolvable graphify CLI (PATH, uv tool, then poetry).
resolve_graphify() {
  if command -v graphify >/dev/null 2>&1; then
    echo "graphify"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    if uv tool run --from graphifyy graphify --help >/dev/null 2>&1; then
      echo "uv tool run --from graphifyy graphify"
      return 0
    fi
  fi
  if command -v poetry >/dev/null 2>&1 && [[ -f pyproject.toml ]]; then
    if poetry run graphify --help >/dev/null 2>&1; then
      echo "poetry run graphify"
      return 0
    fi
  fi
  return 1
}

if ! GRAPHIFY_CMD=$(resolve_graphify); then
  echo '{ "permission": "allow", "agent_message": "graphify-refresh hook skipped: graphify CLI not found." }'
  exit 0
fi

# AST-only incremental update; fail open so prompts are never blocked.
if eval "$GRAPHIFY_CMD update ." >/dev/null 2>&1; then
  echo '{ "permission": "allow", "agent_message": "graphify-refresh hook ran: graphify updated before prompt submit." }'
else
  echo '{ "permission": "allow", "agent_message": "graphify-refresh hook ran but update failed; continuing fail-open." }'
fi

exit 0
