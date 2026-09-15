#!/usr/bin/env bash
# Backup NVS then upload firmware WITHOUT erase_flash (keeps cloud token in NVS).
set -euo pipefail
export PATH="${HOME}/Library/Python/3.9/bin:${PATH}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-/dev/cu.usbmodem101}"
ESPTOOL="$(find "${HOME}/.platformio/packages/tool-esptoolpy" -name esptool.py | head -1)"
BACKUP_DIR="${ROOT}/nvs-backups"
mkdir -p "$BACKUP_DIR"

echo "Port: $PORT"
echo "Put board in download mode: hold BOOT → tap RESET → keep holding BOOT"
echo "Connecting..."

python3 "$ESPTOOL" --chip esp32s3 -p "$PORT" -b 460800 \
  --before default_reset --after no_reset --connect-attempts 20 flash_id

MAC_HEX="$(python3 "$ESPTOOL" --chip esp32s3 -p "$PORT" -b 460800 \
  --before default_reset --after no_reset --connect-attempts 5 read_mac 2>/dev/null \
  | sed -n 's/.*MAC: //p' | head -1 | tr -d ':' | tr 'A-F' 'a-f')"
[[ -n "$MAC_HEX" ]] || MAC_HEX="unknown"
NVS_BIN="${BACKUP_DIR}/nvs-${MAC_HEX}.bin"
echo "Backing up NVS → $NVS_BIN"
python3 "$ESPTOOL" --chip esp32s3 -p "$PORT" -b 460800 \
  --before default_reset --after no_reset --connect-attempts 5 \
  read_flash 0x9000 0x5000 "$NVS_BIN"
cp "$NVS_BIN" "${BACKUP_DIR}/nvs-${MAC_HEX}-$(date +%Y%m%d-%H%M%S).bin"
ls -lh "$NVS_BIN"

echo "Uploading app only (no erase_flash)..."
cd "$ROOT"
pio run -e esp32-s3-rlcd-42 -t upload --upload-port "$PORT"
echo "DONE device=${MAC_HEX}"
