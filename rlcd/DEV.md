# 固件本地开发（`rlcd/`）

统一运行时：`agent-runtime-0.13.x`。用 PlatformIO 环境选择面板。

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

| 环境 | 面板 |
|------|------|
| `esp32-s3-rlcd-42` | ST7305 RLCD 400×300 |
| `esp32-s3-epaper-397` | GxEPD2 ePaper 3.97" 800×480 |

```bash
cd rlcd

# RLCD
pio run -e esp32-s3-rlcd-42 -t upload --upload-port /dev/cu.usbmodem*

# ePaper
pio run -e esp32-s3-epaper-397 -t upload --upload-port /dev/cu.usbmodem*

# 保留 NVS（Wi‑Fi / token）
bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101
pio device monitor -b 115200
```

国内网络慢：[`../scripts/install_from_cn_mirrors.sh`](../scripts/install_from_cn_mirrors.sh)。

## 运行时要点

- `PanelDisplay`：Lua / Pad / 云端路径两块屏共用  
- `http.*`、本机 Pad `http://<ip>/`、`gfx.qr`、`gfx.slow()`（墨水屏为 true）  
- ePaper 默认 **不开 BLE**（给 mbedTLS 留内部堆）；RLCD 可开 `OC-Snake`  
- 墨水屏以 **局刷** 为主；全刷会闪黑白，仅偶尔清残影  

总览见仓库根目录 [`README.md`](../README.md)。
