# Demo：贪食蛇

从云端下发一段 Lua，板子屏幕上出二维码，手机扫码就能玩。全程不用重新烧录。

这个 Demo 演示的是 OnlyClaws 的核心用法：固件只烧一次，应用是热替换的 Lua 脚本。

## 流程

1. 在控制台（或让 Agent）把 [`lua/lan_pad.lua`](lua/lan_pad.lua) 部署到板子上，几秒内开始运行。
2. 蛇从屏幕中间往右走，没人操作的话很快撞墙，屏幕显示 **GAME OVER** 和一个大二维码。
3. 手机扫码，打开板子自带的方向键页面 `http://<板子 IP>`。
4. 点「重新开始」，用 ▲ ▼ ◀ ▶ 控制蛇。

手机直接连板子，不经过云端，所以延迟很低。

## 准备

- 一块已经烧好 OnlyClaws 固件（`agent-runtime ≥ 0.13`）、并在[控制台](https://onlyclaws.world/console/)登记过的板子。RLCD 和 ePaper 都可以。
- 手机和板子连**同一个 Wi‑Fi**。

## 部署

三种方式任选一种。

### 控制台

1. 打开[控制台](https://onlyclaws.world/console/)，选中你的板子。
2. 在「Lua 脚本」里填：名称 `snake-lan`，模式 `loop`，`every_ms` 填 `140`。
3. 把 [`lua/lan_pad.lua`](lua/lan_pad.lua) 的全部内容粘到 `source.lua`。
4. 点「保存并部署到当前设备」。

### 让 Agent 部署

把控制台签发的 `oct_…` 令牌和 [skill.md](https://onlyclaws.world/api/agent/skill.md) 交给 Agent，然后说：

> 把 `demos/snake/lua/lan_pad.lua` 部署到我的设备，名称 `snake-lan`，模式 `loop`，`every_ms` 140。

### curl

```bash
TOKEN=oct_…            # 控制台签发的 Agent 令牌
DEVICE_ID=你的设备ID

curl -sS -X POST https://onlyclaws.world/api/scripts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(DEVICE_ID=$DEVICE_ID python3 - <<'PY'
import json, os
print(json.dumps({
    "name": "snake-lan",
    "language": "lua",
    "mode": "loop",
    "every_ms": 140,
    "device_id": os.environ["DEVICE_ID"],
    "source": open("demos/snake/lua/lan_pad.lua").read(),
}))
PY
)"
```

在仓库根目录执行。

## 怎么玩

| 操作 | 效果 |
|------|------|
| 手机页面 ▲ ▼ ◀ ▶ | 改变方向（不能直接掉头） |
| 手机页面「重新开始」 | 随时重开一局 |
| 板子 KEY 键 | 游戏中向左转；GAME OVER 时重开 |

游戏中屏幕左上角依次显示：

- `sc 3 PAD`：分数，以及手机是否连上（`PAD` 已连上，`..` 还没有）
- 板子 IP，手机也可以直接在浏览器里输入这个地址

GAME OVER 画面显示分数、`Scan to play`、控制地址和二维码。

Wi‑Fi 名称默认不显示，因为它常带着公司或家里的名字，拍照录屏容易露出去。想显示的话，把脚本开头的 `SHOW_SSID` 改成 `true`。

## 常见问题

**扫码后页面打不开。** 先确认手机和板子在同一个 Wi‑Fi。访客网络、公司网络常开着「客户端隔离」，设备之间互相访问不了，换个网络或者用手机热点。

**GAME OVER 画面没有二维码。** 脚本启动时板子还没拿到 IP，等 Wi‑Fi 连上后重新部署一次。如果有 IP 但没有二维码（或显示 `QR fail`），直接在手机浏览器里输入屏幕上的地址也能玩。

**ePaper 上蛇走得很慢。** 电子纸刷新慢，脚本检测到 `gfx.slow()` 后会自动把每步拉长到约 0.9 秒。想玩得流畅用 RLCD。

**怎么停掉。** 在控制台点「停止脚本」，或者部署别的脚本把它替换掉。

## 其他版本

| 脚本 | 怎么控制 | 适合 |
|------|----------|------|
| [`lua/lan_pad.lua`](lua/lan_pad.lua) | 手机扫码，局域网直连板子 | **推荐**，延迟最低 |
| [`lua/key.lua`](lua/key.lua) | 只用板子 KEY 键左转 | 冒烟测试，任何 Lua 运行时都能跑 |
| [`lua/remote_http.lua`](lua/remote_http.lua) | 手机打开 `https://onlyclaws.world/snake/`，板子轮询方向 | 手机和板子不在同一网络时；约 1 秒延迟 |

[`tools/lan_ctrl_server.py`](tools/lan_ctrl_server.py) 是 `remote_http.lua` 的本地实验控制端，正常玩用不到。

## 用到的平台 API

- `gfx.*`、`gfx.qr`（画二维码）、`gfx.slow`（判断电子纸节奏）
- `audio.beep`（吃到食物、撞墙的提示音）
- `input.key`（板载 KEY 键）
- `net.ip`（拼出控制地址）、`net.ssid`（仅在 `SHOW_SSID` 打开时显示）
- `ble.dir`、`ble.restart`、`ble.connected`：读取手机方向键页面（固件 `http_pad`）和 BLE 方向键（仅 RLCD）共用的控制状态
