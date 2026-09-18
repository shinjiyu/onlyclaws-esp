# Demo：MiMo-V2.6 RL 看板

把 [mimo.xiaomi.com/rl](https://mimo.xiaomi.com/rl/) 的训练核心数据拉到 OnlyClaws 屏上。

目标面板：**ePaper 3.97" 800×480** 与 **RLCD 4.2" 400×300**（`gfx.W/H` 自适应布局）。左右双栏，费用按秒本地递增（电子钟）。拉 HTTP 时不改画面、不显示 fetching。约 12 秒交替拉一次 status（pro/flash）；失败退避。本地费用外推不再 30 秒封顶。1 秒刷新数字。

只显示：step、费用、score、roll 进度、token / samples。

## 热部署

```bash
# Agent Token：oct_…（vault: EPAPER_AKI_TOKEN）
# RLCD
DEVICE_ID=a4cb8fdf8440
# ePaper
# DEVICE_ID=441bf6923320

curl -sS -X POST https://onlyclaws.world/epaper/api/scripts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python3 - <<PY
import json
src = open("demos/mimo-rl/lua/board.lua").read()
print(json.dumps({
  "name": "mimo-rl",
  "language": "lua",
  "mode": "loop",
  "every_ms": 1000,
  "device_id": "$DEVICE_ID",
  "source": src,
}))
PY
)"
```
