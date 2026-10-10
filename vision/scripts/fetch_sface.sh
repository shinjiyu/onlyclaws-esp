#!/usr/bin/env bash
# Fetch OpenCV Zoo SFace ONNX into vision/models/ (~38.7 MB).
# Prefer media.githubusercontent (works without HF); digikam mirrors as fallback.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/models/face_recognition_sface_2021dec.onnx"
EXPECTED_SHA="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
EXPECTED_BYTES=38696353
MIN_BYTES=30000000
URLS=(
  "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
  "https://mirrors.sunsite.dk/kde-applicationdata/digikam/facesengine/dnnface/face_recognition_sface_2021dec.onnx"
  "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx"
)
mkdir -p "$(dirname "$OUT")"
sz_have=$(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT" 2>/dev/null || echo 0)
if [[ -f "$OUT" ]] && [[ "$sz_have" -gt "$MIN_BYTES" ]]; then
  echo "already have $OUT ($(du -h "$OUT" | awk '{print $1}'))"
  exit 0
fi
rm -f "$OUT" "$OUT.partial"
for URL in "${URLS[@]}"; do
  echo "downloading SFace → $OUT"
  echo "  from $URL"
  if curl -fL -C - --retry 5 --retry-delay 3 --connect-timeout 30 --max-time 0 \
      -o "$OUT.partial" "$URL"; then
    sz=$(stat -f%z "$OUT.partial" 2>/dev/null || stat -c%s "$OUT.partial")
    if [[ "$sz" -gt "$MIN_BYTES" ]]; then
      mv "$OUT.partial" "$OUT"
      ls -la "$OUT"
      if command -v shasum >/dev/null; then
        got=$(shasum -a 256 "$OUT" | awk '{print $1}')
        if [[ "$got" == "$EXPECTED_SHA" ]]; then
          echo "sha256 OK"
        else
          echo "sha256 mismatch: $got (expected $EXPECTED_SHA)" >&2
        fi
      fi
      exit 0
    fi
    echo "too small ($sz bytes), try next"
    rm -f "$OUT.partial"
  else
    echo "curl failed, try next"
    rm -f "$OUT.partial"
  fi
done
echo "SFace download failed (need ~${EXPECTED_BYTES} bytes)" >&2
exit 1
