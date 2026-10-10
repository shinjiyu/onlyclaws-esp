# JEV servo pathway（OnlyClaws 通路 C）

与 **设备通路 A**（ESP + 云端 wire）、**视觉通路 B**（Host `vision/`）平级。  
**不是** RoArm 固件插件；**不**在云端做轨迹密采样。

## Intent

以 **慢定频** 用 TypeSafe JEV 对每个舵机独立裁判，得到本拍 **安全角区间**；  
区间内任意角都算接受。两拍之间由 **ESP / 舵机** 限速（或二期固件插值）赶到航点。  
决策与目标下发走云；**Cloud carries goals, not trajectories.**

## Shape

```
Vision Host (B)                 JEV Servo Host (C)              Cloud + ESP (A)
snap / latest ──scene.state──►  定频 tick                        │
                                 │  goal + mech + q_all + hist   │
                                 │  并行 N× JEV choose           │
                                 │  → [lo,hi]_j → q*_j           │
                                 └──── 单次 arm.stream(q*,spd) ─►│
                                                                  ▼
                                                            舵机限速到位
                                                            （可选 T_move 插值）
```

编排可落在同一台 Vision Host 进程里，但 **ADL 所有权分开**：C 消费 B 的文本 state，经 A 的 invoke 动臂。

## 决策节拍

| 参数 | 初值 | 说明 |
|------|------|------|
| `T_dec` | 5–15 s | 由 JEV RTT 主导（单次约 1.5–2.5 s）；4 关节 **并行** ≈ 一次 RTT |
| 取景 | 每拍 `vision.snap`（或 `latest` 且 `age_ms` 足够新） | 图不进 JEV |
| 运动 | 拍间 **不再** 打 JEV | 云只发本拍目标一次 |

## 单关节动作语义

JEV 对关节 `j` 选出一档（有限 choice），**后处理换算** 为安全区间：

\[
q_j \in [lo_j, hi_j] \subseteq [q^{\min}_j, q^{\max}_j]
\]

| 规则 | 要求 |
|------|------|
| 合法 | `lo ≤ hi`，宽度 `≥ w_min` |
| 限位 | 裁进机械行程 |
| 单拍幅度 | `\|mid - q_now\| ≤ Δ_max_j`，`mid=(lo+hi)/2` |
| 已在区间内 | 本关节 **不改航点**（等效 stay） |
| 执行航点 | 默认 `mid`；成功判据看拍末 `q` 是否 ∈ `[lo,hi]` |

### Choice → 区间（首期相对当前角）

| choice | 换算 |
|--------|------|
| `stay` | `[q-ε, q+ε]` |
| `toward_neg_s` / `toward_pos_s` | 中心 `q∓δ_s`，半宽 `w` |
| `toward_neg_l` / `toward_pos_l` | 中心 `q∓δ_l`，半宽 `w` |
| `widen_stay`（可选） | 更宽 ε，表示「别大动」 |

具体 `δ_s/δ_l/ε/w` 为结构表常量（每关节可不同）。JEV **不**直接吐连续角。

## 公共 state（所有关节共用）

每次 `choose` 的文本 state 包含：

1. **goal** — 任务目标（稳定短句）
2. **scene** — `SceneDesc.state` + `age_ms`
3. **mech** — 关节角色、限位、`δ`、耦合提示
4. **q_all** — 全体当前角与距限位余量
5. **hist** — 最近 `W` 拍（建议 4–6）：`{t, scene摘要, intervals, q*, reached?}`

每关节只换 `instructions`（「仅裁判关节 j」）与 choice criteria。

## 执行（走云，单次目标）

1. `arm.feedback` → `q_now`
2. 并行 JEV → 区间 → `q*`
3. 若全关节已在各自区间内 → **不** invoke
4. 否则 **一次** `arm.stream(q*, spd)`（oct_ / device_token 云路径）
5. 等待运动窗口（由 `spd` / 可选 `T_move` 覆盖），再 feedback，写 hist

**禁止**：Host 以云 invoke 做 200ms 级密采样插值。  
**允许（二期）**：单条云消息带 `T_move`，**ESP 固件内** lerp。  
**允许（可选热路径）**：本地串口执行 —— 与「决策走云」可并存，另开例外，不作为本通路默认。

## 安全

- 区间裁剪 + `Δ_max`
- JEV 超时 / 非法 choice → 该关节 `stay`
- 看门狗：连续失败停环
- 不把匿名本地 `/js` 当闭环通道（与 RoArm 产品一致）

## Non-goals

- 云端轨迹插值 / 多段密 `stream`
- JEV 输出任意连续角或 IK
- 整图进 JEV；视觉进 ESP
- 把跟随写进 `esp32-roarm-m2` 产品需求

## Requirements

`REQ-JEV-SERVO-TICK`, `REQ-JEV-SERVO-INTERVAL`, `REQ-JEV-SERVO-PER-JOINT`, `REQ-JEV-SERVO-CLOUD-GOAL`, `REQ-JEV-SERVO-HOST-ONLY`

## Code

[`jev_servo/`](../../jev_servo/) — `python -m jev_servo run --goal '...'`

- **默认 `--transport usb`**：Host ↔ ESP USB 串口 JSON（`arm.feedback` / `arm.stream`），毫秒级
- `--transport cloud`：oct_ invoke（慢，设备 poll）
- `--dry-run`：启发式裁判、不动臂

固件需 `agent-runtime-0.16.0+`（`arm_usb_serial`）。

ADR：[decisions/0004-jev-servo-pathway.md](./decisions/0004-jev-servo-pathway.md)
