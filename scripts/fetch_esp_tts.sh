#!/usr/bin/env bash
# Copy Espressif esp-tts (Chinese, concatenative) into rlcd/third_party/esp_tts.
# Headers stay small. The S3 archives and xiaoxin_small.dat are gitignored.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/rlcd/third_party/esp_tts"
SRC="${ESP_TTS_SRC:-/tmp/esp-sr/esp-tts/esp_tts_chinese}"

if [[ ! -f "$SRC/esp_tts_voice_data_xiaoxin_small.dat" ]]; then
  echo "missing $SRC — clone https://github.com/espressif/esp-sr and set ESP_TTS_SRC" >&2
  exit 1
fi

mkdir -p "$DEST/include" "$DEST/esp32s3"
cp "$SRC/include/esp_tts.h" "$SRC/include/esp_tts_voice.h" \
  "$SRC/include/esp_tts_voice_template.h" "$DEST/include/"
cp "$SRC/esp32s3/libesp_tts_chinese.a" "$SRC/esp32s3/libvoice_set_xiaole.a" \
  "$DEST/esp32s3/"
cp "$SRC/esp_tts_voice_data_xiaoxin_small.dat" "$DEST/xiaoxin_small.dat"
echo "esp-tts -> $DEST"
