# 固件本地开发（`rlcd/`）

项目说明：[中文](../README.zh-CN.md) · [English](../README.md)。

统一运行时：`agent-runtime-0.16.x`。核心是 ESP32-S3 裸件，屏、音频、BLE、机械臂都是编译期插件（`oc_features.h` 的 `OC_PLUGIN_*`），按 PlatformIO 环境打开。

| 环境 | 组成 |
|------|------|
| `esp32-s3-bare` | 核心：Wi-Fi、云端、Lua。无面板、无 ES8311 |
| `esp32-s3-rlcd-42` | 核心 + ST7305 400×300 + ES8311 + BLE |
| `esp32-s3-epaper-397` | 核心 + GxEPD2 800×480 + ES8311 |
| `esp32-roarm-m2` | 核心 + STS 机械臂（Waveshare RoArm-M2，classic ESP32，无面板） |

## 环境（macOS arm64）

```bash
python3 -m pip install -U platformio --user
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
pio --version   # 期望 6.x
```

仓库路径示例：`~/Documents/onlyclaws-esp`。

## 密钥

```bash
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
# 编辑 EPD_DEVICE_ID / EPD_DEVICE_TOKEN
```

`device_secrets.h` 已 gitignore。量产/日常烧录优先用 NVS 里的 token，配合：

[`scripts/safe_upload_keep_nvs.sh`](scripts/safe_upload_keep_nvs.sh)

空 token 刷机时不会覆盖 NVS；**非空** flash 凭证会在启动时写回 NVS。

## 构建与烧录

| 环境 | 组成 |
|------|------|
| `esp32-s3-bare` | 无面板、无音频 |
| `esp32-s3-rlcd-42` | ST7305 RLCD 400×300 + 音频 + BLE |
| `esp32-s3-epaper-397` | GxEPD2 ePaper 3.97" 800×480 + 音频 |
| `esp32-roarm-m2` | RoArm-M2 机械臂（classic ESP32，STS @ GPIO18/19，无面板） |

```bash
cd rlcd

# 裸件
pio run -e esp32-s3-bare

# RLCD
pio run -e esp32-s3-rlcd-42 -t upload --upload-port /dev/cu.usbmodem*

# ePaper
pio run -e esp32-s3-epaper-397 -t upload --upload-port /dev/cu.usbmodem*

# RoArm driver board (USB-UART, often /dev/cu.usbserial-*)
pio run -e esp32-roarm-m2 -t upload --upload-port /dev/cu.usbserial-*

# 保留 NVS（Wi‑Fi / token）
bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101
pio device monitor -b 115200
```

国内网络慢：[`../scripts/install_from_cn_mirrors.sh`](../scripts/install_from_cn_mirrors.sh)。

## 运行时要点

- `PanelDisplay`：Lua / Pad / 云端路径两块屏共用；无面板环境走 `panel_plugin` 空实现
- **双 HTTP 通道**（`0.13.3+`）：云端 `pending/status/ack/asset` 用 `tlsCloud`；Lua `http.*` 用 `tlsLua`，互不堵锁  
- **设备身份**（`0.13.4+`）：`device_secrets.h` 只在与本机 MAC 一致时写回 NVS，避免一块板的凭证盖掉另一块  
- `http.*`、本机 Pad `http://<ip>/`、`gfx.qr`、`gfx.slow()`（墨水屏为 true）
- `gfx.image(name, x, y)`（`0.13.5+`）：画云端具名位图，先 `POST /api/bitmaps`，再 `gfx.flush()`。整屏 800×480 不要嵌进 Lua（脚本上限 24000 字节）  
- `/status` meta：`capabilities[]`、`product`（`rlcd-42` / `epaper-397` / `roarm-m2` / `s3-bare`）、`arm` 驱动名。Lua 只注册本机有的模块（无面板就没有 `gfx`，无机械臂就没有 `arm`）  
- ePaper 默认 **不开 BLE**（给 mbedTLS 留内部堆）；RLCD 可开 `OC-Snake`  
- RoArm：**无** factory 匿名 `/js` 关节 API；只用 cloud invoke / Lua `arm.*`  
- 墨水屏以 **局刷** 为主；全刷会闪黑白，仅偶尔清残影  

总览见仓库根目录 [`README.md`](../README.md)；RoArm 产品见 [`doc/structurizr/ROARM-PRODUCT.md`](../doc/structurizr/ROARM-PRODUCT.md)。
