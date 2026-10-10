# Agent operating manual (OnlyClaws ESP)

Architecture authority: [`doc/structurizr/`](doc/structurizr/).  
Same ADL gates as mcp_guard: run `python scripts/adl_check.py` after ADL or requirement changes.

## Order of work

1. Edit `doc/structurizr/model/requirements.json` / `graph.json` / `workspace.dsl` as needed  
2. `python scripts/adl_check.py`  
3. Implement firmware (`rlcd/`) or control plane (`server/`)  
4. Update `COMPONENT-TEST-MAP.md` / `modules-catalog.md`

## Product notes

- Capability plugins: [`doc/structurizr/PLUGIN-RUNTIME.md`](doc/structurizr/PLUGIN-RUNTIME.md)  
- RoArm: [`doc/structurizr/ROARM-PRODUCT.md`](doc/structurizr/ROARM-PRODUCT.md)  
- Vision pathway B: [`doc/structurizr/VISION-PATHWAY.md`](doc/structurizr/VISION-PATHWAY.md) (`vision/`)  
- Do not add `arm` APIs to panel product binaries; do not add `gfx` to RoArm product binaries.  
- Do not put cameras / detectors into ESP firmware; Agent may bridge vision → device invoke.
