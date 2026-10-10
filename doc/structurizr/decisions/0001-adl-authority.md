# 1. Structurizr / ADL is the architecture authority for OnlyClaws ESP

## Status

Accepted

## Context

OnlyClaws ESP will grow into multiple hardware products (panel variants, RoArm, …).  
mcp_guard already enforces two engineering invariants with Structurizr + `adl_check.py`:

1. Business plugin out-degree O(1) (no plugin↔plugin edges)
2. Explicit \(R_{\mathrm{manual}} = R \setminus R_U\)

This repo previously had no checkable ADL.

## Decision

- Adopt **the same tooling** as mcp_guard: `doc/structurizr/workspace.dsl`, `model/graph.json`, `model/requirements.json`, `scripts/adl_check.py`.
- Structurizr-first: change ADL before firmware/control-plane code.
- Backfill existing panel/cloud/Lua behaviour as requirements; record AS-IS monolith debt in graph notes.
- New design (capability plugins + RoArm) lands in ADL docs (`PLUGIN-RUNTIME.md`, `ROARM-PRODUCT.md`) before implementation.

## Consequences

- New features need a `requirements.json` row with `test_kind`.
- New plugins enter `graph.json` / DSL without raising other plugins' out-degree.
- CI/local: `python scripts/adl_check.py` must pass before merge of architecture-affecting work.
