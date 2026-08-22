---
name: graphify-search
description: >-
  Corpus-index navigation for github-analysis. Invoke before lexical search
  (Grep/Glob/Read). Retrieves AST subgraphs via graphify; falls back to source
  reads only on retrieval miss or edit/debug need.
---

# Index Protocol

Ordered retrieval over the repo's AST corpus (`graphify-out/`). Lexical search is secondary.

## Index state

A `beforeSubmitPrompt` hook runs `graphify update .` (AST-only, no LLM cost). Assume the index is synchronized unless you edited sources after the last hook run, the hook failed, or `graphify-out/graph.json` is absent — then run `graphify update .` before retrieval.

## Retrieval sequence

| Priority | Command | Purpose |
|----------|---------|---------|
| 1 | `graphify query "<question>"` | Subgraph for structure, behavior, or cross-file dependencies (BFS) |
| 1′ | `graphify query "<q>" --dfs` | Single causal chain or call path |
| 2 | `graphify path "<A>" "<B>"` | Shortest dependency between symbols |
| 3 | `graphify explain "<concept>"` | Node neighborhood and semantic role |

Navigation aids (when present): `graphify-out/wiki/index.md` before raw files; `graphify-out/GRAPH_REPORT.md` only for architecture when retrieval under-specifies.

## Lexical fallback

Use Grep, Glob, or Read only when retrieval yields no relevant subgraph, confidence is insufficient, the target symbol is missing, or exact line edits are required. Scope reads narrowly.

## Bootstrap

```bash
graphify update .
```

Corpus scope is governed by `.graphifyignore` (excludes `data/`, `results/`, `analysis-results/`).

## Subagent directive

Propagate this sequence to any subagent performing code exploration. Do not bypass the index because paths are familiar — the graph surfaces INFERRED edges lexical search cannot recover.
