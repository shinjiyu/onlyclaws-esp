#!/usr/bin/env python3
"""OnlyClaws tools as an MCP server (JSON-RPC 2.0, stdlib only).

Exposes a handful of OnlyClaws control-plane calls as MCP tools so a voice
assistant such as Xiaozhi can drive an OnlyClaws board. Every tool maps to an
existing REST endpoint in ``server/app.py`` and authenticates with an Agent
control token (``oct_…``).

Run directly for stdio (Cursor / Claude Desktop / mcp_pipe.py), or use
``xiaozhi_bridge.py`` to serve it over the Xiaozhi MCP endpoint websocket.

Env:
  ONLYCLAWS_TOKEN       required, Agent control token ``oct_…`` (console → Agent tokens)
  ONLYCLAWS_BASE_URL    default https://onlyclaws.world
  ONLYCLAWS_DEVICE_ID   default device id (otherwise the server picks your first device)
  ONLYCLAWS_ALLOW_LUA   set to 1 to expose ``onlyclaws_deploy_lua`` (off by default)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "onlyclaws-xiaozhi", "version": "0.1.0"}
USER_AGENT = "onlyclaws-xiaozhi-mcp/0.1"
LUA_MAX_BYTES = 24000  # SCRIPT_SOURCE_MAX in server/app.py
HTTP_TIMEOUT = 10.0


class Config:
    def __init__(self, env: Optional[dict[str, str]] = None) -> None:
        env = dict(os.environ if env is None else env)
        self.token = (env.get("ONLYCLAWS_TOKEN") or "").strip()
        self.base_url = (env.get("ONLYCLAWS_BASE_URL") or "https://onlyclaws.world").rstrip("/")
        self.device_id = (env.get("ONLYCLAWS_DEVICE_ID") or "").strip().lower() or None
        self.allow_lua = (env.get("ONLYCLAWS_ALLOW_LUA") or "").strip().lower() in ("1", "true", "yes")


class ApiError(RuntimeError):
    pass


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def tool_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def api(cfg: Config, method: str, path: str, body: Optional[dict[str, Any]] = None,
        query: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Call the OnlyClaws REST API with the oct_ bearer. Raises ApiError on failure."""
    if not cfg.token:
        raise ApiError("ONLYCLAWS_TOKEN is not set (mint an oct_ token in the OnlyClaws console)")
    if not cfg.token.startswith("oct_"):
        raise ApiError("ONLYCLAWS_TOKEN must be an Agent control token (oct_…), not a device token")
    url = cfg.base_url + path
    if query:
        q = {k: v for k, v in query.items() if v not in (None, "")}
        if q:
            url += "?" + urllib.parse.urlencode(q)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg.token}",
        "User-Agent": USER_AGENT,
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code == 401:
            raise ApiError("401 unauthorized: the oct_ token is invalid or revoked; mint a new one in the console") from e
        raise ApiError(f"HTTP {e.code} {method} {path}: {detail}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"cannot reach {cfg.base_url}: {e.reason}") from e
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise ApiError(f"non-JSON response from {path}") from e
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _device(cfg: Config, args: dict[str, Any]) -> Optional[str]:
    did = str(args.get("device_id") or "").strip().lower()
    return did or cfg.device_id


DEVICE_ID_PROP = {
    "type": "string",
    "description": "OnlyClaws device id, e.g. a4cb8fdf8440. Optional; defaults to ONLYCLAWS_DEVICE_ID.",
}

BASE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "onlyclaws_devices",
        "description": "列出我的 OnlyClaws 板子：在线状态、型号、能力、温湿度和电量。List my OnlyClaws boards with online state, product, capabilities, temperature/humidity and battery.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "onlyclaws_show_text",
        "description": "在 OnlyClaws 屏幕上显示一张文字卡片（标题+正文），默认提示音。Show a text card (title + body) on the board's panel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title"},
                "body": {"type": "string", "description": "Body text, up to 4000 chars"},
                "beep": {"type": "boolean", "description": "Beep on arrival (default true)"},
                "device_id": DEVICE_ID_PROP,
            },
            "required": ["body"],
        },
    },
    {
        "name": "onlyclaws_beep",
        "description": "让 OnlyClaws 板子响一声，用来找设备或提醒。Make the board beep.",
        "inputSchema": {"type": "object", "properties": {"device_id": DEVICE_ID_PROP}},
    },
    {
        "name": "onlyclaws_recent_events",
        "description": "读取板子上 Lua 脚本通过 emit() 上报的最新事件。Read the latest events emitted by the board's Lua script.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "How many (default 5)"},
                "device_id": DEVICE_ID_PROP,
            },
        },
    },
    {
        "name": "onlyclaws_script_status",
        "description": "查看板子上当前 Lua 脚本的运行状态和错误。Get the running Lua script's state and last error.",
        "inputSchema": {"type": "object", "properties": {"device_id": DEVICE_ID_PROP}},
    },
    {
        "name": "onlyclaws_stop_script",
        "description": "停止板子上正在运行的 Lua 脚本。Stop the Lua script running on the board.",
        "inputSchema": {"type": "object", "properties": {"device_id": DEVICE_ID_PROP}},
    },
]

DEPLOY_LUA_TOOL: dict[str, Any] = {
    "name": "onlyclaws_deploy_lua",
    "description": (
        "把一段 Lua 脚本部署到 OnlyClaws 板子并运行（会替换当前脚本）。"
        "Deploy and run a Lua script on the board, replacing the current one. "
        "Hooks: on_start() / on_loop(). APIs: gfx.clear/text/flush, audio.beep, sensors(), emit(name, table)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Script name"},
            "source": {"type": "string", "description": "Lua source, max 24000 bytes"},
            "mode": {"type": "string", "enum": ["once", "loop"], "description": "once or loop (default once)"},
            "every_ms": {"type": "integer", "minimum": 50, "description": "Loop interval in ms (default 1000)"},
            "device_id": DEVICE_ID_PROP,
        },
        "required": ["name", "source"],
    },
}


def list_tools(cfg: Config) -> list[dict[str, Any]]:
    return BASE_TOOLS + ([DEPLOY_LUA_TOOL] if cfg.allow_lua else [])


SENSOR_KEYS = ("temp_c", "humidity", "battery_pct", "battery_v", "charging", "product", "script_state")


def _summarize_device(d: dict[str, Any]) -> dict[str, Any]:
    meta = d.get("meta") or {}
    out: dict[str, Any] = {
        "id": d.get("id"),
        "name": d.get("name"),
        "online": d.get("online"),
        "last_seen": d.get("last_seen"),
        "fw": d.get("fw"),
    }
    if meta.get("capabilities") is not None:
        out["capabilities"] = meta.get("capabilities")
    for k in SENSOR_KEYS:
        if k in meta:
            out[k] = meta[k]
    return out


def call_tool(cfg: Config, name: Optional[str], args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "onlyclaws_devices":
            body = api(cfg, "GET", "/api/devices")
            return tool_result({"devices": [_summarize_device(d) for d in body.get("devices") or []]})

        if name == "onlyclaws_show_text":
            text = str(args.get("body") or "")
            title = str(args.get("title") or "")
            if not text.strip() and not title.strip():
                return tool_result("body or title is required", is_error=True)
            payload = {
                "title": title[:120],
                "body": text[:4000],
                "beep": bool(args.get("beep", True)),
                "device_id": _device(cfg, args),
            }
            body = api(cfg, "POST", "/api/push", payload)
            msg = body.get("message") or {}
            return tool_result({"ok": True, "message_id": msg.get("id"), "device_id": msg.get("device_id")})

        if name == "onlyclaws_beep":
            body = api(cfg, "POST", "/api/action", {"beep": True, "device_id": _device(cfg, args)})
            msg = body.get("message") or {}
            return tool_result({"ok": True, "message_id": msg.get("id"), "device_id": msg.get("device_id")})

        if name == "onlyclaws_recent_events":
            try:
                limit = int(args.get("limit") or 5)
            except (TypeError, ValueError):
                limit = 5
            limit = max(1, min(limit, 50))
            body = api(cfg, "GET", "/api/events", query={"device_id": _device(cfg, args), "limit": limit})
            events = [
                {k: e.get(k) for k in ("name", "data", "created_at", "device_id")}
                for e in body.get("events") or []
            ]
            return tool_result({"events": events})

        if name == "onlyclaws_script_status":
            body = api(cfg, "GET", "/api/script/status", query={"device_id": _device(cfg, args)})
            keys = ("device_id", "script_id", "script_state", "script_error", "fw", "last_seen")
            return tool_result({k: body.get(k) for k in keys})

        if name == "onlyclaws_stop_script":
            body = api(cfg, "POST", "/api/script/stop", {"device_id": _device(cfg, args)})
            return tool_result({"ok": True, "device_id": body.get("device_id")})

        if name == "onlyclaws_deploy_lua":
            if not cfg.allow_lua:
                return tool_result("onlyclaws_deploy_lua is disabled; set ONLYCLAWS_ALLOW_LUA=1", is_error=True)
            source = str(args.get("source") or "")
            if not source.strip():
                return tool_result("source is required", is_error=True)
            if len(source.encode("utf-8")) > LUA_MAX_BYTES:
                return tool_result(f"source exceeds {LUA_MAX_BYTES} bytes", is_error=True)
            device_id = _device(cfg, args)
            if not device_id:
                # POST /api/scripts only deploys when device_id is present.
                return tool_result("device_id is required (or set ONLYCLAWS_DEVICE_ID)", is_error=True)
            mode = args.get("mode") if args.get("mode") in ("once", "loop") else "once"
            payload = {
                "name": str(args.get("name") or "xiaozhi")[:120],
                "language": "lua",
                "mode": mode,
                "every_ms": int(args.get("every_ms") or 1000),
                "source": source,
                "device_id": device_id,
            }
            body = api(cfg, "POST", "/api/scripts", payload)
            script = body.get("script") or {}
            deployed = bool((body.get("deploy") or {}).get("success"))
            return tool_result({"ok": deployed, "script_id": script.get("id"), "device_id": device_id, "mode": mode},
                               is_error=not deployed)

        return tool_result(f"unknown tool: {name}", is_error=True)
    except ApiError as e:
        return tool_result(str(e), is_error=True)
    except Exception as e:  # noqa: BLE001 - never crash the session on a tool error
        return tool_result(f"{type(e).__name__}: {e}", is_error=True)


def handle(cfg: Config, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Handle one JSON-RPC message. Returns a response, or None for notifications."""
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if "method" not in msg:  # a response to something we never sent; ignore
        return None
    if mid is None:  # notification
        return None
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": list_tools(cfg)})
    if method == "tools/call":
        return ok(call_tool(cfg, params.get("name"), params.get("arguments") or {}))
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def handle_line(cfg: Config, line: str) -> Optional[str]:
    """Parse one JSON-RPC text frame/line and return the serialized reply (or None)."""
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    if isinstance(msg, list):
        out = [r for m in msg if isinstance(m, dict) and (r := handle(cfg, m)) is not None]
        return json.dumps(out, ensure_ascii=False) if out else None
    if not isinstance(msg, dict):
        return None
    resp = handle(cfg, msg)
    return json.dumps(resp, ensure_ascii=False) if resp is not None else None


def main() -> None:
    cfg = Config()
    eprint(f"onlyclaws-xiaozhi MCP (stdio) base={cfg.base_url} lua={'on' if cfg.allow_lua else 'off'}")
    for line in sys.stdin:
        reply = handle_line(cfg, line)
        if reply is not None:
            print(reply, flush=True)


if __name__ == "__main__":
    main()
