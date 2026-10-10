# Vision pathway（主机侧）

OnlyClaws **通路 B**：相机帧 → **动态物体名** + 空描述 + 紧凑 state。  
**不是** ESP 固件插件，也不是 RoArm 产品的一部分。

设计见 [`doc/structurizr/VISION-PATHWAY.md`](../doc/structurizr/VISION-PATHWAY.md)。

## 依赖

- Python 3.9+
- OpenCV (`cv2`) + ONNX 模型：
  - `models/face_detection_yunet_2023mar.onnx` — 人脸检测
  - `models/face_recognition_sface_2021dec.onnx` — 人脸特征 / 编号（可选）
  - `models/yolov8n.onnx` — **COCO-80 动态物体**（杯、人、椅、笔记本…）

首次没有 YOLO / SFace 权重时：

```bash
bash vision/scripts/fetch_models.sh   # YOLO
bash vision/scripts/fetch_sface.sh    # SFace ~37MB
```

人脸编号画廊（通路 C presence 默认开启）：

```bash
python3 -m jev_servo faces list
python3 -m jev_servo faces rename 1 aki
# gallery: jev_servo/runs/face_gallery/gallery.json
```

运行时 **不需要** ultralytics，只要 OpenCV 读 ONNX。

```bash
cd /path/to/onlyclaws-esp
python3 -m vision path/to.jpg
python3 -m vision path/to.jpg --json
python3 -m vision path/to.jpg --no-coco --blobs   # 退回显著性 blob
python3 vision/tests/test_pipeline.py
```

## 热环输出示例

```text
person@0.18,0.60 span=0.65 left-mid s=0.85; bus@0.51,0.45 span=0.97 center-mid s=0.88; empty@…
```

类名来自 COCO（`cell_phone`、`laptop`、`cup`…）。桌面白纸这类「非 COCO」场景可能为空，属正常；可再开 `--blobs` 补无标签团块。
