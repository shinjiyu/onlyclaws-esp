# OnlyClaws ESP Structurizr / ADL

## Authority

| Artifact | Role |
|----------|------|
| [workspace.dsl](./workspace.dsl) | C4 model (human + Structurizr) |
| [model/graph.json](./model/graph.json) | Checkable dependency graph |
| [model/requirements.json](./model/requirements.json) | Feature set \(R\) |
| [ADL-RULES.md](./ADL-RULES.md) | O(1) + \(R_{\mathrm{manual}}\) rules |
| [modules-catalog.md](./modules-catalog.md) | Module contracts |
| [COMPONENT-TEST-MAP.md](./COMPONENT-TEST-MAP.md) | Req ↔ test map |
| [decisions/](./decisions/) | ADRs |
| [PLUGIN-RUNTIME.md](./PLUGIN-RUNTIME.md) | Target: capability plugins |
| [ROARM-PRODUCT.md](./ROARM-PRODUCT.md) | RoArm product + motor passthrough |
| [VISION-PATHWAY.md](./VISION-PATHWAY.md) | Pathway B: host vision → objects + empties |
| [JEV-SERVO-PATHWAY.md](./JEV-SERVO-PATHWAY.md) | Pathway C: host JEV per-joint intervals → one cloud goal |
| [PRESENCE-FOLLOW-PATHWAY.md](./PRESENCE-FOLLOW-PATHWAY.md) | Pathway C task: face presence + traverse/follow (no FK/IMU) |

Tooling matches **mcp_guard**: copy of `scripts/adl_check.py` (same gates).

## Check

```bash
python scripts/adl_check.py
# or from another cwd:
python scripts/adl_check.py --root /path/to/onlyclaws-esp
```

Exit 0 only if: plugin \(\mathrm{out}\le K\), no plugin→plugin edges, no `test_kind: none`, and every `unit`/`contract` req has a non-empty `tests` list.

Prints \(R_{\mathrm{manual}}\) for human / device QA.

## Formalism

Same O(1) plugin + \(R_U\) / \(R_{\mathrm{manual}}\) split as mcp_guard.
