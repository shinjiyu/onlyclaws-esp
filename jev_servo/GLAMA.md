# Glama listing (stdio MCP)

This directory’s `Dockerfile` is the Glama build target for OnlyClaws presence MCP (`mcp_server.py`).

- Starts stdio JSON-RPC and answers `initialize` + `tools/list` **without** USB arm / tip-cam / console.
- `JEV_MCP_NO_SPAWN=1` prevents auto-spawning `http://127.0.0.1:8765` during health checks.
- For real arm tools on a workstation: `bash jev_servo/run_mcp.sh` (or `python3 -m jev_servo mcp`) with the console running.

## Remaining human steps (no public submit API)

Glama’s directory API is **read-only**; adding a server requires a logged-in browser + GitHub OAuth:

1. Open https://glama.ai/mcp/servers and sign in with GitHub (`shinjiyu`).
2. Click **Add MCP Server**.
3. Repository URL: `https://github.com/shinjiyu/onlyclaws-esp`
4. Display name / description: e.g. “OnlyClaws presence MCP” — stdio tools for RoArm tip-cam presence ops.
5. If the admin UI asks for a Dockerfile path, use `jev_servo/Dockerfile`.
6. Wait for the health check (initialize + tools/list) to pass.
7. Confirm listing is live: `https://glama.ai/mcp/servers/shinjiyu/onlyclaws-esp` returns HTTP 200 (not 404).
8. Then update [awesome-mcp-servers#16449](https://github.com/punkpeye/awesome-mcp-servers/pull/16449) with:

```
[![shinjiyu/onlyclaws-esp MCP server](https://glama.ai/mcp/servers/shinjiyu/onlyclaws-esp/badges/score.svg)](https://glama.ai/mcp/servers/shinjiyu/onlyclaws-esp)
```

Root `glama.json` lists `shinjiyu` as maintainer for ownership claim after the listing exists.
