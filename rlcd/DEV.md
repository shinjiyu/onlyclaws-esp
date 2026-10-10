# 固件本地开发（`rlcd/`）

统一运行时：`agent-runtime-0.15.x`。用 PlatformIO 环境选择面板 / RoArm 与 `OC_CAP_*` 能力集。

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

| 环境 | 产品 |
|------|------|
| `esp32-s3-rlcd-42` | ST7305 RLCD 400×300 |
| `esp32-s3-epaper-397` | GxEPD2 ePaper 3.97" 800×480 |
| `esp32-roarm-m2` | Waveshare RoArm-M2（classic ESP32，STS @ GPIO18/19，无面板） |

```bash
cd rlcd

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

- `PanelDisplay`：Lua / Pad / 云端路径两块屏共用；RoArm 用 `HeadlessPanel`
- **双 HTTP 通道**（`0.13.3+`）：云端 `pending/status/ack/asset` 用 `tlsCloud`；Lua `http.*` 用 `tlsLua`，互不堵锁  
- **设备身份**（`0.13.4+`）：`device_secrets.h` 只在与本机 MAC 一致时写回 NVS，避免一块板的凭证盖掉另一块  
- `/status` meta：`capabilities[]`、`product`（`rlcd-42` / `epaper-397` / `roarm-m2`）、`arm` 驱动名  
- `http.*`、本机 Pad `http://<ip>/`、`gfx.qr`、`gfx.slow()`（墨水屏为 true）  
- ePaper 默认 **不开 BLE**（给 mbedTLS 留内部堆）；RLCD 可开 `OC-Snake`  
- RoArm：**无** factory 匿名 `/js` 关节 API；只用 cloud invoke / Lua `arm.*`  
- 墨水屏以 **局刷** 为主；全刷会闪黑白，仅偶尔清残影  

总览见仓库根目录 [`README.md`](../README.md)；RoArm 产品见 [`doc/structurizr/ROARM-PRODUCT.md`](../doc/structurizr/ROARM-PRODUCT.md)。
