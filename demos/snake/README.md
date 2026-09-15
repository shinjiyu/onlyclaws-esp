# Demo：贪食蛇

OnlyClaws ESP 上的边缘 Lua 小游戏，用来演示「Agent 热部署 loop 脚本 + 板端 API」。  
**不是**控制面本身。

支持 RLCD（快）与 ePaper（慢刷新，脚本内用 `gfx.slow()` 拉长步进）。

## 变体

| 脚本 | 输入 | 固件要求 |
|------|------|----------|
| [`lua/key.lua`](lua/key.lua) | KEY 左转 | 任意 Lua 运行时 |
| [`lua/lan_pad.lua`](lua/lan_pad.lua) | 手机打开 `http://<板IP>/` | `agent-runtime ≥ 0.13` |
| [`lua/remote_http.lua`](lua/remote_http.lua) | 轮询外部 `CTRL/dir` | `http.get`（≥ 0.11） |

**推荐** `lan_pad.lua`：板子本机提供方向键页，延迟低，任意浏览器可用。

## 云端部署

```bash
# Agent Token：oct_…
curl -sS -X POST https://onlyclaws.world/epaper/api/scripts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python3 - <<'PY'
import json
src = open("demos/snake/lua/lan_pad.lua").read()
print(json.dumps({
  "name": "snake-lan",
  "language": "lua",
  "mode": "loop",
  "every_ms": 140,
  "device_id": "你的设备ID",
  "source": src,
}))
PY
)"
```

手机与板同一 Wi‑Fi，打开屏上或 Game Over 二维码中的地址（例如 `http://192.168.101.51/`）。

## 可选：PC 控制端

[`tools/lan_ctrl_server.py`](tools/lan_ctrl_server.py) 仅给 `remote_http.lua` 实验用。  
主路径请用板端 Pad。

## 用到的平台 API

- `gfx.*`、`gfx.qr`、`gfx.slow` · `audio.beep` · `input.key` · `net.ip` / `net.ssid`
- 本机 Pad：固件 `http_pad` + `pad_ctrl`（RLCD 上还可选 BLE）
