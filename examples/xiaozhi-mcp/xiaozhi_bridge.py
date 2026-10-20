#!/usr/bin/env python3
"""Connect the OnlyClaws MCP tools to a Xiaozhi MCP endpoint (接入点).

The Xiaozhi endpoint is a websocket URL you copy from the Xiaozhi console
(``wss://…/mcp/?token=…``). The cloud dials *nothing*: this process connects
out to that URL, then answers JSON-RPC requests (``initialize``, ``tools/list``,
``tools/call``) that arrive as text frames — the same wire pattern as
78/mcp-calculator's ``mcp_pipe.py``, but serving the tools in-process instead
of piping a child process.

Env:
  XIAOZHI_MCP_ENDPOINT  required (``MCP_ENDPOINT`` is accepted as a fallback)
  ONLYCLAWS_*           see onlyclaws_mcp.py

Usage:
  pip install -r requirements.txt
  python xiaozhi_bridge.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from typing import Any, Optional

import websockets

import onlyclaws_mcp as oc

log = logging.getLogger("xiaozhi-bridge")

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 300.0


def redact(url: str) -> str:
    """Hide the endpoint token when logging."""
    return re.sub(r"((?:token|access_token)=)[^&\s]+", r"\1***", url)


async def serve_connection(ws: Any, cfg: oc.Config) -> None:
    """Answer JSON-RPC frames on one open websocket until it closes."""
    async for frame in ws:
        if isinstance(frame, bytes):
            frame = frame.decode("utf-8", "replace")
        # HTTP calls are blocking; keep them off the event loop so pings still flow.
        reply = await asyncio.to_thread(oc.handle_line, cfg, frame)
        if reply is not None:
            await ws.send(reply)


async def run(endpoint: str, cfg: oc.Config, connect: Any = None,
              max_attempts: Optional[int] = None) -> None:
    """Connect with exponential backoff and serve forever (or ``max_attempts`` times)."""
    connect = connect or websockets.connect
    backoff = INITIAL_BACKOFF
    attempt = 0
    while max_attempts is None or attempt < max_attempts:
        attempt += 1
        try:
            log.info("connecting to %s", redact(endpoint))
            async with connect(endpoint) as ws:
                log.info("connected; serving %d tools", len(oc.list_tools(cfg)))
                backoff = INITIAL_BACKOFF
                await serve_connection(ws, cfg)
            log.warning("endpoint closed the connection")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("connection error: %s", redact(str(e)))
        if max_attempts is not None and attempt >= max_attempts:
            break
        log.info("reconnecting in %.0fs", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    endpoint = (os.environ.get("XIAOZHI_MCP_ENDPOINT") or os.environ.get("MCP_ENDPOINT") or "").strip()
    if not endpoint:
        log.error("set XIAOZHI_MCP_ENDPOINT to the MCP endpoint URL from the Xiaozhi console")
        return 2
    cfg = oc.Config()
    if not cfg.token.startswith("oct_"):
        log.error("set ONLYCLAWS_TOKEN to an Agent control token (oct_…)")
        return 2
    try:
        asyncio.run(run(endpoint, cfg))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
