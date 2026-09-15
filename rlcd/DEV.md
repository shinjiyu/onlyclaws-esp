# RLCD firmware — local dev

## Prerequisites (macOS arm64)

```bash
python3 -m pip install -U platformio --user
export PATH="$HOME/Library/Python/3.9/bin:$PATH"   # adjust if needed
pio --version   # expect 6.x
```

Repo path used here: `~/Documents/onlyclaws-esp`.

## Secrets

```bash
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
# edit EPD_DEVICE_ID / EPD_DEVICE_TOKEN for your board
```

`device_secrets.h` is gitignored. Prefer NVS tokens in the field; use
[`scripts/safe_upload_keep_nvs.sh`](scripts/safe_upload_keep_nvs.sh) so flash does not wipe them.

## Build

```bash
cd rlcd
pio run -e esp32-s3-rlcd-42
```

China / slow networks: see [`../scripts/install_from_cn_mirrors.sh`](../scripts/install_from_cn_mirrors.sh).

## Upload

```bash
pio run -e esp32-s3-rlcd-42 -t upload --upload-port /dev/cu.usbmodem*
# or keep NVS:
bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101
pio device monitor -b 115200
```

## Runtime notes (`agent-runtime-0.13.x`)

Shared Lua/pad runtime; panel via `PanelDisplay`:

| PlatformIO env | Panel |
|----------------|--------|
| `esp32-s3-rlcd-42` | ST7305 RLCD 400×300 |
| `esp32-s3-epaper-397` | GxEPD2 3.97" 800×480 |

APIs: `http.*`, LAN pad `http://<ip>/`, BLE, `gfx.qr`, `gfx.slow()` (true on e-ink).

```bash
pio run -e esp32-s3-rlcd-42
pio run -e esp32-s3-epaper-397 -t upload --upload-port /dev/cu.usbmodem*
```
