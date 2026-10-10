#!/usr/bin/env bash
# Backup NVS then upload firmware WITHOUT erase_flash (keeps cloud token in NVS).
#
# Usage:
#   bash scripts/safe_upload_keep_nvs.sh [PORT] [ENV]
# Examples:
#   bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101
#   bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101 esp32-s3-rlcd-42
#   bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbserial-110 esp32-roarm-m2
set -euo pipefail
export PATH="${HOME}/Library/Python/3.9/bin:${PATH}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-/dev/cu.usbmodem101}"
ENV_NAME="${2:-esp32-s3-rlcd-42}"
ESPTOOL="$(find "${HOME}/.platformio/packages/tool-esptoolpy" -name esptool.py | head -1)"
BACKUP_DIR="${ROOT}/nvs-backups"
mkdir -p "$BACKUP_DIR"

case "$ENV_NAME" in
  esp32-roarm-m2) CHIP=esp32; NVS_OFF=0x9000; NVS_LEN=0x5000 ;;
  *) CHIP=esp32s3; NVS_OFF=0x9000; NVS_LEN=0x5000 ;;
esac

echo "Port: $PORT  env: $ENV_NAME  chip: $CHIP"
if [[ "$CHIP" == "esp32s3" ]]; then
  echo "Put board in download mode: hold BOOT → tap RESET → keep holding BOOT"
fi
echo "Connecting..."

python3 "$ESPTOOL" --chip "$CHIP" -p "$PORT" -b 460800 \
  --before default_reset --after no_reset --connect-attempts 20 flash_id

MAC_HEX="$(python3 "$ESPTOOL" --chip "$CHIP" -p "$PORT" -b 460800 \
  --before default_reset --after no_reset --connect-attempts 5 read_mac 2>/dev/null \
  | sed -n 's/.*MAC: //p' | head -1 | tr -d ':' | tr 'A-F' 'a-f')"
[[ -n "$MAC_HEX" ]] || MAC_HEX="unknown"
NVS_BIN="${BACKUP_DIR}/nvs-${MAC_HEX}.bin"
echo "Backing up NVS → $NVS_BIN"
python3 "$ESPTOOL" --chip "$CHIP" -p "$PORT" -b 460800 \
  --before default_reset --after no_reset --connect-attempts 5 \
  read_flash "$NVS_OFF" "$NVS_LEN" "$NVS_BIN"
cp "$NVS_BIN" "${BACKUP_DIR}/nvs-${MAC_HEX}-$(date +%Y%m%d-%H%M%S).bin"
ls -lh "$NVS_BIN"

echo "Uploading app only (no erase_flash)..."
cd "$ROOT"
pio run -e "$ENV_NAME" -t upload --upload-port "$PORT"
echo "DONE device=${MAC_HEX} env=${ENV_NAME}"
