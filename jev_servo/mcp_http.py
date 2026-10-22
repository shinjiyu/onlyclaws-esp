#!/usr/bin/env python3
"""Streamable-HTTP style MCP endpoint wrapping mcp_server primitives.

POST /mcp  JSON-RPC (initialize | tools/list | tools/call | ping)
Auth: Authorization: Bearer <ARM_MCP_HTTP_TOKEN>

Env:
  ARM_MCP_HTTP_HOST  default 127.0.0.1
  ARM_MCP_HTTP_PORT  default 8787
  ARM_MCP_HTTP_TOKEN required (or file ARM_MCP_HTTP_TOKEN_FILE)
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
import uvicorn

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo import mcp_server as m  # noqa: E402


def _token() -> str:
    t = os.environ.get("ARM_MCP_HTTP_TOKEN") or ""
    if t:
        return t.strip()
    path = os.environ.get("ARM_MCP_HTTP_TOKEN_FILE")
    if path and Path(path).is_file():
        return Path(path).read_text().strip()
    raise SystemExit("ARM_MCP_HTTP_TOKEN or ARM_MCP_HTTP_TOKEN_FILE required")


TOKEN = _token()
HOST = os.environ.get("ARM_MCP_HTTP_HOST", "127.0.0.1")
PORT = int(os.environ.get("ARM_MCP_HTTP_PORT", "8787"))

app = FastAPI(title="onlyclaws-presence-http", version=m.SERVER_INFO["version"])


def _check_auth(authorization: Optional[str]) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    got = authorization.split(" ", 1)[1].strip()
    if got != TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")


def _enrich_cam_grab(result: dict[str, Any]) -> dict[str, Any]:
    """If tools/call returned cam_grab JSON text, attach base64 for remote agents."""
    try:
        content = result.get("content") or []
        if not content or content[0].get("type") != "text":
            return result
        data = json.loads(content[0]["text"])
        path = data.get("path")
        if path and Path(path).is_file() and data.get("ok"):
            raw = Path(path).read_bytes()
            # cap ~900KB payload
            if len(raw) <= 900_000:
                data["jpeg_base64"] = base64.b64encode(raw).decode("ascii")
                data["jpeg_bytes"] = len(raw)
            content[0]["text"] = json.dumps(data, ensure_ascii=False, indent=2)
            result["content"] = content
    except Exception:
        pass
    return result


def _dispatch(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    resp = m.handle(msg)
    if resp is None:
        return None
    # enrich cam_grab on tools/call success
    if msg.get("method") == "tools/call" and "result" in resp:
        name = (msg.get("params") or {}).get("name")
        if name == "cam_grab" and isinstance(resp["result"], dict):
            resp["result"] = _enrich_cam_grab(resp["result"])
    return resp


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "server": m.SERVER_INFO, "transport": "streamable-http-json"}


@app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
async def mcp_endpoint(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Response:
    _check_auth(authorization)
    if request.method == "GET":
        # Minimal: no long-lived SSE; clients using pure JSON POST still work.
        return JSONResponse(
            {
                "error": "use POST JSON-RPC to /mcp",
                "server": m.SERVER_INFO,
            },
            status_code=405,
        )
    if request.method == "DELETE":
        return Response(status_code=204)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    if isinstance(body, list):
        out = [r for item in body if isinstance(item, dict) and (r := _dispatch(item)) is not None]
        return JSONResponse(out)

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="object or array required")

    # notifications may have no id
    resp = _dispatch(body)
    if resp is None:
        return Response(status_code=202)
    return JSONResponse(resp)


def main() -> None:
    m.eprint(f"MCP HTTP on http://{HOST}:{PORT}/mcp (Bearer auth)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
