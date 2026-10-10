# Vision pathway（OnlyClaws 通路 B）

与 **设备通路（ESP 固件 + 云端 wire）** 平级，**不是** RoArm / panel 产品的一部分。

## Intent

把相机帧在 **视觉主机（Vision Host）** 上快速压成结构化描述，供 Agent / JEV 类文本裁判使用：

| 输出 | 含义 |
|------|------|
| **对象描述** | 检测到的实体：类别、归一化中心、跨度、分数 |
| **空描述** | 未被对象占据的自由区域（网格合并） |
| **紧凑 state 行** | 单行文本，适合离散动作选择，不喂整图 |

**不做：** 把 UVC / YOLO / VLM 编进 ESP32；不把视觉闭环写进 `esp32-roarm-m2`。

## Shape

```
Camera (USB / CSI / RTSP)
        │
        ▼
┌───────────────────────┐
│  Vision Host          │  Mac 开发机 · 或车上 SBC/Jetson/NPU 盒
│  vision/ pipeline     │
│  detectors → empties  │
│  → SceneDesc + state  │
└───────────┬───────────┘
            │  text / JSON（本机 / LAN / 云）
            ▼
   Agent / JEV / tools / **通路 C（JEV 舵机环）**
            │  optional · C：单次云 goal，非密轨迹
            ▼
   Device pathway (oct_ invoke → panel / arm / wheel …)
```

设备通路与视觉通路 **只通过 Agent / 通路 C 编排偶合**；ADL 上无插件边、无固件依赖。通路 C 契约见 [`JEV-SERVO-PATHWAY.md`](./JEV-SERVO-PATHWAY.md)。

## 摄像头放哪：部署分层（含轮式）

相机永远挂在 **Vision Host** 上，不挂在 ESP。换形态 = 换 Host，不换通路契约。

| 阶段 | Vision Host | 相机 | 典型场景 |
|------|-------------|------|----------|
| **B0 现况** | 桌上 Mac / PC | USB UVC 插电脑 | 台架臂、算法开发 |
| **B1 半车载** | 车上树莓派 / Orange Pi（同 Wi‑Fi） | USB 或 CSI 插 SBC | 轮式原型，仍可云端 Agent |
| **B2 车载热环** | Jetson / RK3588 / 带 NPU 的盒 | CSI / GMSL / USB3 | 要跟轮速、低延迟避障 |
| **B3 远程眼** | 车上 Host 推 RTSP/WebRTC；描述可在车端或边云 | 同上 | 远程遥控 + 本地热环 |

**轮式推荐默认：B1→B2**

```
┌──────────── 车体 ────────────┐
│  摄像头 ──► Vision Host      │  ← 跑 vision/（同一套 SceneDesc）
│               │ state         │
│               ▼               │
│         本机 Agent 或          │
│         上报 onlyclaws.world  │
│               │               │
│  ESP（轮/臂驱动）◄── invoke   │  ← 仍是通路 A，只管电机
└──────────────────────────────┘
```

要点：

1. **ESP 仍然不吃图像** — 轮式也只收 `arm.*` / 未来 `wheel.*` 这类短指令。  
2. **`vision/` 契约不变** — Mac 与车上 SBC 共用同一 `SceneDesc` / state 行；换的是进程跑在哪。  
3. **图不过云做热环** — 热环在 Vision Host 本地；云端最多收 state 或抽帧冷环。  
4. **多相机** — 仍是 Host 侧多路 ingest（前视/侧视），合并进一份 scene 或分 `camera_id` 字段；不进 ESP。

不推荐：把 UVC 接到 ESP32-CAM 当主视觉（算力/稳定性不够撑热环）；也不推荐整图长期经蜂窝上传做闭环。

## Latency tiers

| 档 | 用途 | 实现（首期） |
|----|------|--------------|
| **热环** | 每帧 / 几十 ms | **YOLOv8n COCO-80**（动态物体名）+ YuNet 人脸；网格空区；紧凑 state（**Vision Host 本地**） |
| **温环** | 丢目标重找 / 非 COCO 物 | 显著性 blob 兜底、或更大模型 / 轻量 caption |
| **冷环** | 人工叙事 | 外部 VLM — 非本通路默认；可边云 |

## Contract（`SceneDesc`）

见 `vision/schema.py`：

- `objects[]`: `{kind, u, v, span, score, …}` — `u,v ∈ [0,1]` 图像归一化
- `empties[]`: `{region, u, v, area, …}` — 自由空间块
- `state`: 一行字符串，例如  
  `face@0.62,0.41 span=0.18; blob@0.20,0.70 span=0.12; empty@right-upper area=0.22; empty@left-mid area=0.15`

空间词：`left|center|right` × `upper|mid|lower`（由 `u,v` 派生）。

后续可加可选字段：`camera_id`、`host`（dev-mac / rover-sbc），不破坏现有消费者。

## Non-goals

- 不在 ESP 上跑视觉
- 不把「跟随 / 搜索 / 导航」写进 RoArm 产品需求
- 不把整图当 JEV `state`（先描述后裁判）
- 不把「电脑插摄像头」写成终态——那只是 B0

## Requirements

`REQ-VISION-SCENE`, `REQ-VISION-EMPTY`, `REQ-VISION-STATE`, `REQ-VISION-HOST-ONLY`

## Code

[`vision/`](../../vision/) — `python -m vision path/to.jpg`
