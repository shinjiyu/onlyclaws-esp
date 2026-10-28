"""Preset scripts per device kind (ESP32 Lua, OCA JS). See ADR 0009.

Only server/ is deployed, so the sources live in server/presets/ as copies of
demos/ and android/. `python presets.py sync` refreshes them; tests check drift.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

SERVER_DIR = Path(__file__).resolve().parent
PRESETS_DIR = SERVER_DIR / "presets"
REPO_ROOT = SERVER_DIR.parent

KINDS = ("esp32", "oca")

PRESETS: list[dict[str, Any]] = [
    {
        "id": "snake-lan",
        "kind": "esp32",
        "file": "esp32/snake-lan.lua",
        "origin": "demos/snake/lua/lan_pad.lua",
        "mode": "loop",
        "every_ms": 140,
        "needs": ["panel"],
        "title": {"zh": "贪吃蛇 · 手机方向键", "en": "Snake · phone D-pad"},
        "summary": {
            "zh": "撞墙后屏幕出二维码，同一 Wi‑Fi 的手机扫码打开板子自带的方向键页面来玩。",
            "en": "Game over shows a QR code; a phone on the same Wi‑Fi opens the board's own D-pad page.",
        },
    },
    {
        "id": "snake-remote",
        "kind": "esp32",
        "file": "esp32/snake-remote.lua",
        "origin": "demos/snake/lua/remote_http.lua",
        "mode": "loop",
        "every_ms": 140,
        "needs": ["panel"],
        "title": {"zh": "贪吃蛇 · 云端遥控", "en": "Snake · cloud remote"},
        "summary": {
            "zh": "方向来自 onlyclaws.world/snake/ 公共遥控页，手机不用和板子在同一网络。",
            "en": "Directions come from the public page onlyclaws.world/snake/; no shared network needed.",
        },
    },
    {
        "id": "snake-key",
        "kind": "esp32",
        "file": "esp32/snake-key.lua",
        "origin": "demos/snake/lua/key.lua",
        "mode": "loop",
        "every_ms": 140,
        "needs": ["panel"],
        "title": {"zh": "贪吃蛇 · 单键", "en": "Snake · one key"},
        "summary": {
            "zh": "只用板载 KEY：按一下左转，结束后再按重开。适合验证热部署。",
            "en": "Board KEY only: press to turn left, press again after game over. Good hot-deploy check.",
        },
    },
    {
        "id": "wifi-rssi",
        "kind": "esp32",
        "file": "esp32/wifi-rssi.lua",
        "origin": "demos/wifi-rssi/lua/board.lua",
        "mode": "loop",
        "every_ms": 4000,
        "needs": ["panel"],
        "title": {"zh": "Wi‑Fi 信号", "en": "Wi‑Fi signal"},
        "summary": {
            "zh": "把 RSSI 换成 5 格信号和一句能做什么（能视频、只能网页、经常断），带最近几十分钟的曲线和掉线次数。",
            "en": "Turns RSSI into 5 bars and what the link is good for (video, web only, drops), with a recent graph and drop count.",
        },
    },
    {
        "id": "mimo-rl",
        "kind": "esp32",
        "file": "esp32/mimo-rl.lua",
        "origin": "demos/mimo-rl/lua/board.lua",
        "mode": "loop",
        "every_ms": 1000,
        "needs": ["panel"],
        "title": {"zh": "MiMo RL 时钟", "en": "MiMo RL clock"},
        "summary": {
            "zh": "显示小米 MiMo-V2.6 强化学习训练进度和花费，RLCD 和墨水屏自适应。",
            "en": "Shows Xiaomi MiMo-V2.6 RL training progress and cost; fits RLCD and ePaper.",
        },
    },
    {
        "id": "kws-yes-no",
        "kind": "esp32",
        "file": "esp32/kws-yes-no.lua",
        "origin": "demos/kws-yes-no/main.lua",
        "mode": "loop",
        "every_ms": 200,
        "needs": ["panel", "ml"],
        "title": {"zh": "语音 yes / no", "en": "Voice yes / no"},
        "summary": {
            "zh": "板子本地识别 yes / no 并上报事件。需要先在 /api/ml/models 上传 micro_speech 模型。",
            "en": "On-device yes / no spotting with events. Upload the micro_speech model to /api/ml/models first.",
        },
    },
    {
        "id": "bird-detect",
        "kind": "esp32",
        "file": "esp32/bird-detect.lua",
        "origin": "demos/bird-detect/main.lua",
        "mode": "loop",
        "every_ms": 200,
        "needs": ["panel", "ml"],
        "title": {"zh": "鸟叫检测", "en": "Bird detector"},
        "summary": {
            "zh": "每 3 秒听一次，听到鸟叫就上报。需要先上传 bird_detect 模型。",
            "en": "Listens in 3 s windows and reports birdsong. Upload the bird_detect model first.",
        },
    },
    {
        "id": "arm-hold",
        "kind": "esp32",
        "file": "esp32/arm-hold.lua",
        "origin": "demos/arm-hold/lua/board.lua",
        "mode": "loop",
        "every_ms": 5000,
        "needs": ["arm"],
        "title": {"zh": "机械臂 · 保持姿态", "en": "RoArm · hold pose"},
        "summary": {
            "zh": "RoArm 专用：读一次当前姿态并上报，然后原地保持。",
            "en": "RoArm only: reads the current pose once, reports it, then holds.",
        },
    },
    {
        "id": "bilibili-play",
        "kind": "oca",
        "file": "oca/bilibili-play.js",
        "origin": "android/scripts/bilibili-play.js",
        "needs": ["container"],
        "title": {"zh": "B 站陪看（bilibili play）", "en": "Bilibili play"},
        "summary": {
            "zh": "DeepSeek 驱动的 B 站浏览助手：看热门、搜索、读字幕总结和评论，桌面上显示它在看什么。点赞、投币、关注、评论默认关闭，在手机上逐项打开。首次运行在手机桌面填 DeepSeek key，并登录 B 站。",
            "en": "A DeepSeek-driven Bilibili browser: hot lists, search, subtitle summaries and comments, shown on the phone desk. Like, coin, follow and comment are off until you enable each one on the phone. First run asks for a DeepSeek key on the desk and a Bilibili login.",
        },
    },
    {
        "id": "oca-empty",
        "kind": "oca",
        "file": "oca/empty.js",
        "origin": "android/app/src/main/assets/boot.js",
        "needs": ["container"],
        "title": {"zh": "空容器", "en": "Empty container"},
        "summary": {
            "zh": "只打印一行“容器已就绪”。用来停掉正在跑的脚本。",
            "en": "Logs one line and does nothing else. Use it to stop the running script.",
        },
    },
]

_BY_ID = {p["id"]: p for p in PRESETS}


def get(preset_id: str) -> Optional[dict[str, Any]]:
    return _BY_ID.get((preset_id or "").strip().lower())


def path_of(preset: dict[str, Any]) -> Path:
    return PRESETS_DIR / preset["file"]


def source(preset: dict[str, Any]) -> str:
    return path_of(preset).read_text(encoding="utf-8")


def language(preset: dict[str, Any]) -> str:
    return "lua" if preset["kind"] == "esp32" else "js"


def public(preset: dict[str, Any]) -> dict[str, Any]:
    path = path_of(preset)
    out = {
        "id": preset["id"],
        "kind": preset["kind"],
        "language": language(preset),
        "filename": Path(preset["file"]).name,
        "title": preset["title"],
        "summary": preset["summary"],
        "needs": list(preset.get("needs") or []),
        "bytes": path.stat().st_size if path.is_file() else 0,
    }
    if preset["kind"] == "esp32":
        out["mode"] = preset["mode"]
        out["every_ms"] = preset["every_ms"]
    return out


def list_presets(kind: Optional[str] = None) -> list[dict[str, Any]]:
    k = (kind or "").strip().lower()
    return [public(p) for p in PRESETS if not k or p["kind"] == k]


def drift() -> list[str]:
    """Preset ids whose server copy differs from its origin (origins missing are skipped)."""
    out = []
    for p in PRESETS:
        origin = REPO_ROOT / p["origin"]
        if not origin.is_file():
            continue
        if not path_of(p).is_file() or origin.read_bytes() != path_of(p).read_bytes():
            out.append(p["id"])
    return out


def sync() -> list[str]:
    changed = []
    for p in PRESETS:
        origin = REPO_ROOT / p["origin"]
        dst = path_of(p)
        data = origin.read_bytes()
        if dst.is_file() and dst.read_bytes() == data:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        changed.append(p["id"])
    return changed


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "sync":
        print("updated:", ", ".join(sync()) or "none")
    else:
        bad = drift()
        print("drift:", ", ".join(bad) or "none")
        sys.exit(1 if bad else 0)
