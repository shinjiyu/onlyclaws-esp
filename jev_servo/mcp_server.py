#!/usr/bin/env python3
"""Presence / tip-cam arm MCP for Cursor (stdio JSON-RPC, no third-party deps).

Talks to the local jev_servo console HTTP API (default http://127.0.0.1:8765).
If the console is down, tools that need it will try to start it once.

Env:
  JEV_CONSOLE_URL   default http://127.0.0.1:8765
  JEV_MCP_NO_SPAWN  if set, never auto-start the console
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "onlyclaws-presence", "version": "0.1.0"}
BASE_URL = os.environ.get("JEV_CONSOLE_URL", "http://127.0.0.1:8765").rstrip("/")
_NO_SPAWN = bool(os.environ.get("JEV_MCP_NO_SPAWN"))


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def tool_result(text: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _http(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
    url = BASE_URL + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": "onlyclaws-presence-mcp/0.1"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except urllib.error.URLError as e:
        raise ConnectionError(f"console unreachable at {BASE_URL}: {e}") from e
    try:
        parsed: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"raw": raw[:2000]}
    if isinstance(parsed, dict):
        parsed.setdefault("http_status", status)
    return parsed


def console_up() -> bool:
    try:
        _http("GET", "/api/status?after=0", timeout=1.5)
        return True
    except Exception:
        return False


def ensure_console() -> dict[str, Any]:
    if console_up():
        return {"ok": True, "running": True, "spawned": False, "url": BASE_URL}
    if _NO_SPAWN:
        raise RuntimeError(
            f"console not running at {BASE_URL}; start: "
            f"python3 -m jev_servo console --host 127.0.0.1 --http-port 8765"
        )
    eprint(f"spawning console at {BASE_URL} …")
    host = "127.0.0.1"
    port = 8765
    try:
        u = urllib.parse.urlparse(BASE_URL)
        if u.hostname:
            host = u.hostname
        if u.port:
            port = u.port
    except Exception:
        pass
    log_path = _ROOT / "jev_servo" / "runs" / "mcp-console.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 — kept for child lifetime
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "jev_servo",
            "console",
            "--host",
            host,
            "--http-port",
            str(port),
        ],
        cwd=str(_ROOT),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(40):
        time.sleep(0.25)
        if console_up():
            return {
                "ok": True,
                "running": True,
                "spawned": True,
                "url": BASE_URL,
                "log": str(log_path),
            }
    raise RuntimeError(f"console failed to start; see {log_path}")


def _slim_status(st: dict[str, Any], *, log_limit: int = 12) -> dict[str, Any]:
    logs = st.get("logs") or []
    slim_logs = []
    for e in logs[-log_limit:]:
        if not isinstance(e, dict):
            continue
        slim_logs.append(
            {
                "seq": e.get("seq"),
                "kind": e.get("kind"),
                "line": (e.get("line") or "")[:240],
            }
        )
    lt = st.get("last_tick") or {}
    return {
        "running": st.get("running"),
        "tick_count": st.get("tick_count"),
        "config": st.get("config"),
        "scene": st.get("scene"),
        "last_error": st.get("last_error"),
        "last_tick": {
            "mission": (lt.get("search") or {}).get("mission") if isinstance(lt, dict) else None,
            "choices": lt.get("choices") if isinstance(lt, dict) else None,
            "q": lt.get("q") if isinstance(lt, dict) else None,
            "stream_status": lt.get("stream_status") if isinstance(lt, dict) else None,
        }
        if lt
        else None,
        "logs": slim_logs,
        "url": BASE_URL,
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "arm_ensure_console",
        "description": (
            "Ensure the local presence console is up (http://127.0.0.1:8765). "
            "Starts it in the background if needed."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "arm_status",
        "description": (
            "Status of the tip-cam presence loop: running, ticks, config, scene, "
            "last choices, recent log lines."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "log_limit": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 50,
                    "default": 12,
                    "description": "How many recent log lines to include",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "arm_ops",
        "description": "List finite presence ops (find_any / find_id / follow) and help text.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "arm_start",
        "description": (
            "Start a presence op on the physical arm (MOVES THE ARM). "
            "Ops: find_any (stow→sweep→follow any face), find_id (need face_id), "
            "follow (no global sweep). Requires console; will spawn it if down."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "op": {
                    "type": "string",
                    "enum": ["find_any", "find_id", "follow"],
                    "default": "find_any",
                },
                "face_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Required for find_id; optional filter for follow",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, do not stream to the arm",
                },
                "spd": {"type": "integer", "minimum": 50, "maximum": 800, "default": 200},
                "transport": {"type": "string", "enum": ["usb", "cloud"], "default": "usb"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "arm_stop",
        "description": "Stop the running presence loop (finishes current tick).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "arm_snap",
        "description": (
            "Grab one tip-cam frame and run YuNet(+optional SFace). Does not move the arm. "
            "Returns scene string and presence fields."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "identify": {
                    "type": "boolean",
                    "default": True,
                    "description": "Match / enroll SFace gallery ids",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "arm_faces",
        "description": "List enrolled tip-cam face gallery ids/names (SFace).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def call_tool(name: str, arguments: Optional[dict[str, Any]]) -> dict[str, Any]:
    args = arguments or {}
    try:
        if name == "arm_ensure_console":
            return tool_result(json.dumps(ensure_console(), ensure_ascii=False, indent=2))

        if name == "arm_ops":
            ensure_console()
            body = _http("GET", "/api/ops")
            return tool_result(json.dumps(body, ensure_ascii=False, indent=2))

        if name == "arm_status":
            ensure_console()
            st = _http("GET", "/api/status?after=0")
            lim = int(args.get("log_limit") or 12)
            return tool_result(
                json.dumps(_slim_status(st, log_limit=lim), ensure_ascii=False, indent=2)
            )

        if name == "arm_start":
            ensure_console()
            op = str(args.get("op") or "find_any")
            payload: dict[str, Any] = {
                "op": op,
                "dry_run": bool(args.get("dry_run", False)),
                "spd": int(args.get("spd") or 200),
                "transport": str(args.get("transport") or "usb"),
            }
            if args.get("face_id") is not None:
                payload["face_id"] = int(args["face_id"])
            body = _http("POST", "/api/start", payload)
            return tool_result(json.dumps(body, ensure_ascii=False, indent=2), is_error=not body.get("ok", True))

        if name == "arm_stop":
            ensure_console()
            body = _http("POST", "/api/stop", {})
            return tool_result(json.dumps(body, ensure_ascii=False, indent=2))

        if name == "arm_snap":
            from jev_servo.presence import presence_from_scene
            from jev_servo.vision_snap import snap_scene

            identify = bool(args.get("identify", True))
            snap = snap_scene(perceive="person", identify=identify, enroll_unknown=True)
            scene = snap.get("scene") or ""
            pres = presence_from_scene(scene)
            out = {
                "source": snap.get("source"),
                "ms": snap.get("ms"),
                "scene": scene,
                "presence": pres.as_dict(),
            }
            return tool_result(json.dumps(out, ensure_ascii=False, indent=2))

        if name == "arm_faces":
            from vision.identity import FaceGallery, sface_available

            gal = FaceGallery()
            out = {
                "path": str(gal.json_path),
                "sface": sface_available(),
                "faces": gal.list_faces(),
            }
            return tool_result(json.dumps(out, ensure_ascii=False, indent=2))

        return tool_result(f"unknown tool: {name}", is_error=True)
    except Exception as e:
        return tool_result(f"{type(e).__name__}: {e}", is_error=True)


def handle(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        return ok(call_tool(params.get("name"), params.get("arguments") or {}))
    if method == "ping":
        return ok({})
    if method and str(method).startswith("notifications/"):
        return None
    return err(-32601, f"Method not found: {method}")


def main() -> None:
    eprint(f"onlyclaws-presence MCP starting console={BASE_URL}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            eprint("bad json line")
            continue
        if isinstance(msg, list):
            out = [r for m in msg if (r := handle(m)) is not None]
            if out:
                print(json.dumps(out), flush=True)
            continue
        resp = handle(msg)
        if resp is not None:
            print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()
