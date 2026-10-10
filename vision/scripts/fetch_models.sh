#!/usr/bin/env bash
# Fetch / export vision models into vision/models/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="$ROOT/models"
mkdir -p "$MODELS"
cd "$MODELS"

if [[ ! -f face_detection_yunet_2023mar.onnx ]]; then
  echo "YuNet: copy from mcp_guard roarm_ident/models or OpenCV zoo"
fi

if [[ ! -f yolov8n.onnx ]]; then
  echo "Exporting YOLOv8n ONNX (needs ultralytics once)…"
  python3 - <<'PY'
from pathlib import Path
from ultralytics import YOLO
dest = Path("yolov8n.onnx")
m = YOLO("yolov8n.pt")
out = Path(m.export(format="onnx", imgsz=320, simplify=True, opset=12))
if out.resolve() != dest.resolve():
    dest.write_bytes(out.read_bytes())
print("wrote", dest, dest.stat().st_size)
PY
fi

ls -lh "$MODELS"
echo "Runtime needs only OpenCV + these ONNX files (not ultralytics)."
