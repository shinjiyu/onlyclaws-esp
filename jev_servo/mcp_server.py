#!/usr/bin/env python3
"""RoArm + tip-cam primitive MCP for Cursor (stdio JSON-RPC).

Exposes low-level USB tools only — not presence loops, named poses, or recording.

  arm.connect / disconnect / feedback / stream / stop / torque / hold
  cam.info / grab

Env:
  ARM_USB_PORT      default /dev/cu.usbserial-110 (else auto)
  ARM_FRAME_DIR     default ~/Documents/mcp_guard/tmp/arm_frame  (QuietArmUsb)
  MCP_GUARD_ROOT    default ~/Documents/mcp_guard               (tip-cam LiveCam)
  ARM_MCP_NO_LIMIT  if set, skip joint absolute/step clamps (dangerous)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "onlyclaws-presence", "version": "0.3.0"}

_DEFAULT_GUARD = Path.home() / "Documents" / "mcp_guard"
MCP_GUARD_ROOT = Path(
    os.environ.get("MCP_GUARD_ROOT") or _DEFAULT_GUARD
).expanduser().resolve()
ARM_FRAME_DIR = Path(
    os.environ.get("ARM_FRAME_DIR") or (MCP_GUARD_ROOT / "tmp" / "arm_frame")
).expanduser().resolve()
DEFAULT_PORT = os.environ.get("ARM_USB_PORT", "/dev/cu.usbserial-110")
_NO_LIMIT = bool(os.environ.get("ARM_MCP_NO_LIMIT"))

# Absolute joint limits (radians). Same spirit as roarm_ident.hw.ABS_LIMIT + shoot J0_MAX.
ABS_LO = [-1.50, -1.35, -0.85, -1.60]
ABS_HI = [1.65, 1.35, 2.60, 1.60]
# Max |Δq| per stream call (radians).
STEP_MAX = [0.45, 0.22, 0.28, 0.60]

_arm: Any = None  # QuietArmUsb | ArmUsb
_arm_port: str | None = None


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def tool_result(text: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _ok(obj: Any) -> dict[str, Any]:
    return tool_result(json.dumps(obj, ensure_ascii=False, indent=2))


def _err(msg: str) -> dict[str, Any]:
    return tool_result(msg, is_error=True)


def _ensure_paths() -> None:
    for p in (str(MCP_GUARD_ROOT), str(ARM_FRAME_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _round_q(q: list[float]) -> list[float]:
    return [round(float(x), 4) for x in q[:4]]


def _clamp_target(cur: list[float], target: list[float]) -> tuple[list[float], list[str]]:
    """Return (clamped_q, warnings)."""
    if _NO_LIMIT:
        return [float(x) for x in target[:4]], []
    out: list[float] = []
    warns: list[str] = []
    for i in range(4):
        t = float(target[i])
        c = float(cur[i])
        lo, hi = ABS_LO[i], ABS_HI[i]
        if t < lo:
            warns.append(f"q[{i}] {t:.3f} < {lo}; clamped")
            t = lo
        elif t > hi:
            warns.append(f"q[{i}] {t:.3f} > {hi}; clamped")
            t = hi
        step = STEP_MAX[i]
        if abs(t - c) > step + 1e-6:
            t2 = c + step if t > c else c - step
            warns.append(f"q[{i}] step {t - c:+.3f} > ±{step}; limited to {t2:.3f}")
            t = t2
        out.append(t)
    return out, warns


def _get_arm():
    global _arm
    if _arm is None:
        raise RuntimeError("arm not connected; call arm_connect first")
    return _arm


def arm_connect(port: str | None = None) -> dict[str, Any]:
    global _arm, _arm_port
    if _arm is not None:
        try:
            q = _arm.feedback()
            return {
                "ok": True,
                "already": True,
                "port": _arm_port,
                "q": _round_q(q),
            }
        except Exception:
            try:
                _arm.close()
            except Exception:
                pass
            _arm = None
            _arm_port = None

    _ensure_paths()
    port = port or DEFAULT_PORT
    try:
        from arm_quiet import QuietArmUsb  # type: ignore

        arm = QuietArmUsb(port=port)
    except Exception as exc:
        # Fallback: plain ArmUsb auto-port
        from jev_servo.arm_usb import ArmUsb, find_port

        use = port if Path(port).exists() else find_port()
        eprint(f"QuietArmUsb failed ({exc}); falling back to ArmUsb on {use}")
        arm = ArmUsb(port=use)
        port = use

    q = arm.feedback()
    _arm = arm
    _arm_port = port
    return {"ok": True, "already": False, "port": port, "q": _round_q(q)}


def arm_disconnect() -> dict[str, Any]:
    global _arm, _arm_port
    if _arm is None:
        return {"ok": True, "was_open": False}
    try:
        _arm.close()
    finally:
        _arm = None
        _arm_port = None
    return {"ok": True, "was_open": True}


def _cam_module():
    _ensure_paths()
    from roarm_ident.hw import LiveCam, resolve_usb_cam  # type: ignore

    return LiveCam, resolve_usb_cam


def cam_info() -> dict[str, Any]:
    import subprocess

    prefer = None
    try:
        _, resolve_usb_cam = _cam_module()
        prefer = resolve_usb_cam()
    except Exception as exc:
        prefer = f"(resolve failed: {exc})"

    cams: list[dict[str, str]] = []
    try:
        raw = subprocess.check_output(
            ["system_profiler", "SPCameraDataType", "-json"], text=True
        )
        data = json.loads(raw)
        for cam in data.get("SPCameraDataType") or []:
            uid = str(cam.get("spcamera_unique-id") or "")
            name = str(cam.get("_name") or "")
            if uid:
                cams.append({"name": name, "unique_id": uid})
    except Exception as exc:
        return {"ok": False, "error": str(exc), "prefer": prefer}

    tip = [c for c in cams if "0bda3035" in c["unique_id"].lower()]
    return {
        "ok": True,
        "prefer_tip": prefer,
        "tip_candidates": tip,
        "all": cams,
    }


def cam_grab(
    *,
    out: str | None = None,
    width: int = 960,
    identify: bool = False,
) -> dict[str, Any]:
    import cv2

    LiveCam, resolve_usb_cam = _cam_module()
    uid = resolve_usb_cam()
    t0 = time.perf_counter()
    with LiveCam(uid) as cam:
        for _ in range(4):
            cam.bgr()
        bgr, _gen = cam.bgr()
    h, w = bgr.shape[:2]
    if width and w > width:
        bgr = cv2.resize(bgr, (width, int(h * width / w)))
        h, w = bgr.shape[:2]

    if out:
        path = Path(out).expanduser()
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = ARM_FRAME_DIR / "rec" / "mcp_grabs" / f"tip_{stamp}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

    result: dict[str, Any] = {
        "ok": True,
        "unique_id": uid,
        "path": str(path),
        "size": [w, h],
        "ms": int((time.perf_counter() - t0) * 1000),
    }

    if identify:
        # Optional: scene string via pathway-B. Still a single grab, not a loop.
        from jev_servo.presence import presence_from_scene
        from jev_servo.vision_snap import snap_scene

        snap = snap_scene(
            image=path, perceive="person", identify=True, enroll_unknown=True
        )
        scene = snap.get("scene") or ""
        result["scene"] = scene
        result["presence"] = presence_from_scene(scene).as_dict()

    return result


TOOLS: list[dict[str, Any]] = [
    {
        "name": "arm_help",
        "description": (
            "Primitive RoArm+tip-cam MCP help. Tools are USB-level only "
            "(connect/feedback/stream/stop/torque/hold + cam grab). "
            "No find_any / goto / record wrappers."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "arm_connect",
        "description": (
            "Open USB serial to the RoArm ESP32 (QuietArmUsb: DTR/RTS low). "
            "Call once before stream/feedback. Returns current q radians."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {
                    "type": "string",
                    "description": "Serial device, default /dev/cu.usbserial-110",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "arm_disconnect",
        "description": "Close the USB serial session.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "arm_feedback",
        "description": (
            "Read current joint radians q=[base,shoulder,elbow,wrist]. "
            "Does not move. Requires arm_connect."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "arm_stream",
        "description": (
            "MOVES THE ARM. Send arm.stream target q (4 radians) and spd "
            "(servo steps/s, ~50-800). Absolute and per-call step clamps apply "
            "unless ARM_MCP_NO_LIMIT=1. Requires arm_connect. "
            "Prefer small steps; read feedback between moves."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "Target [base, shoulder, elbow, wrist] radians",
                },
                "spd": {
                    "type": "integer",
                    "minimum": 20,
                    "maximum": 800,
                    "default": 120,
                },
            },
            "required": ["q"],
            "additionalProperties": False,
        },
    },
    {
        "name": "arm_stop",
        "description": "Send arm.stop on the USB protocol (halt motion). Requires arm_connect.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "arm_torque",
        "description": (
            "Enable/disable servo torque (arm.torque). on=false lets you drag the arm; "
            "call arm_hold or arm_torque on=true before leaving. Requires arm_connect."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "on": {"type": "boolean", "description": "true=engage, false=free drag"}
            },
            "required": ["on"],
            "additionalProperties": False,
        },
    },
    {
        "name": "arm_hold",
        "description": (
            "Re-engage hold at the current pose (arm.hold). Use after torque off / drag. "
            "Returns q. Requires arm_connect."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "cam_info",
        "description": "List Mac cameras and the preferred tip-cam Unique ID (Realtek 0bda3035).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "cam_grab",
        "description": (
            "Grab one tip-cam JPEG to disk. Does not move the arm. "
            "Optional identify=true runs YuNet+SFace once on that frame."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {
                    "type": "string",
                    "description": "JPEG path; default ARM_FRAME_DIR/rec/mcp_grabs/tip_*.jpg",
                },
                "width": {
                    "type": "integer",
                    "minimum": 160,
                    "maximum": 1920,
                    "default": 960,
                },
                "identify": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, also return scene/presence from one-shot vision",
                },
            },
            "additionalProperties": False,
        },
    },
]


def call_tool(name: str, arguments: Optional[dict[str, Any]]) -> dict[str, Any]:
    args = arguments or {}
    try:
        if name == "arm_help":
            return _ok(
                {
                    "server": SERVER_INFO,
                    "port_default": DEFAULT_PORT,
                    "arm_frame_dir": str(ARM_FRAME_DIR),
                    "mcp_guard_root": str(MCP_GUARD_ROOT),
                    "protocol": {
                        "feedback": '→ {"tool":"arm.feedback"} ← {"ok":true,"q":[b,s,e,h]}',
                        "stream": '→ {"tool":"arm.stream","q":[...],"spd":N} ← {"ok":true}',
                        "stop": '→ {"tool":"arm.stop"}',
                        "torque": '→ {"tool":"arm.torque","on":bool}',
                        "hold": '→ {"tool":"arm.hold"} ← {"ok":true,"q":[...]}',
                    },
                    "limits": {
                        "abs_lo": ABS_LO,
                        "abs_hi": ABS_HI,
                        "step_max": STEP_MAX,
                        "disabled": _NO_LIMIT,
                    },
                    "workflow": [
                        "arm_connect",
                        "arm_feedback",
                        "cam_grab (optional)",
                        "arm_stream small deltas + arm_feedback",
                        "arm_stop if needed",
                        "arm_disconnect when done",
                    ],
                    "safety": [
                        "Ask user before arm_stream / arm_torque(false).",
                        "q is radians [base,shoulder,elbow,wrist]; base abs max 1.65.",
                        "Do not hold the serial port open across long idle periods.",
                        "If board enters download mode, disconnect and tell the user to reset.",
                    ],
                }
            )

        if name == "arm_connect":
            port = args.get("port")
            return _ok(arm_connect(str(port) if port else None))

        if name == "arm_disconnect":
            return _ok(arm_disconnect())

        if name == "arm_feedback":
            arm = _get_arm()
            q = arm.feedback()
            return _ok({"ok": True, "port": _arm_port, "q": _round_q(q)})

        if name == "arm_stream":
            arm = _get_arm()
            q_in = args.get("q")
            if not isinstance(q_in, list) or len(q_in) < 4:
                return _err("q must be an array of 4 numbers (radians)")
            spd = int(args.get("spd") or 120)
            cur = arm.feedback()
            target, warns = _clamp_target(cur, [float(x) for x in q_in[:4]])
            status = arm.stream(target, spd)
            after = arm.feedback()
            return _ok(
                {
                    "ok": True,
                    "status": status,
                    "spd": spd,
                    "requested": _round_q([float(x) for x in q_in[:4]]),
                    "commanded": _round_q(target),
                    "before": _round_q(cur),
                    "after": _round_q(after),
                    "warnings": warns,
                }
            )

        if name == "arm_stop":
            arm = _get_arm()
            status = arm.stop()
            q = arm.feedback()
            return _ok({"ok": True, "status": status, "q": _round_q(q)})

        if name == "arm_torque":
            if "on" not in args:
                return _err("on (boolean) required")
            arm = _get_arm()
            on = bool(args["on"])
            status = arm.torque(on)
            q = None
            try:
                q = _round_q(arm.feedback())
            except Exception:
                pass
            return _ok({"ok": True, "status": status, "on": on, "q": q})

        if name == "arm_hold":
            arm = _get_arm()
            q = arm.hold()
            return _ok({"ok": True, "q": _round_q(q)})

        if name == "cam_info":
            return _ok(cam_info())

        if name == "cam_grab":
            out = args.get("out")
            width = int(args.get("width") or 960)
            identify = bool(args.get("identify", False))
            return _ok(
                cam_grab(
                    out=str(out) if out else None,
                    width=width,
                    identify=identify,
                )
            )

        return _err(f"unknown tool: {name}")
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


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
    eprint(
        f"onlyclaws-presence MCP primitives v{SERVER_INFO['version']} "
        f"port={DEFAULT_PORT} guard={MCP_GUARD_ROOT}"
    )
    try:
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
    finally:
        try:
            arm_disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
