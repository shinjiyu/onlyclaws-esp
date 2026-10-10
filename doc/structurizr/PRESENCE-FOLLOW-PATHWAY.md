# Presence / Traverse / Follow（通路 C 任务形态）

与 **JEV-SERVO-PATHWAY** 同属主机通路 C，但是**简化任务**：

| 要 | 不要 |
|----|------|
| tip 相机判断**人在不在**，并给 **face#id** 落盘 | 世界坐标 / tip 朝向终点空间 |
| 机械臂**关节空间遍历**搜索 | 依赖不准的 FK 当主测量 |
| 看见后**粗跟随**把脸留在画面里 | 雅可比图像伺服、IMU |

「识别」= YuNet 检出 + **SFace 特征**匹配画廊编号（可改名）。不是证件级核验。

## Face ID

- 库目录：`jev_servo/runs/face_gallery/gallery.json`
- 未知脸自动 enroll 下一编号并 save；已知脸余弦 ≥ 0.36 复用 id
- CLI：`python -m jev_servo faces list` / `faces rename 3 名字`
- 模型：`vision/models/face_recognition_sface_2021dec.onnx`（`bash vision/scripts/fetch_sface.sh`）
- 无 SFace 时退回颜色直方图嵌入（仅开发）

State 例：`face#3(aki)@0.50,0.40 span=0.20 center-mid s=0.91`

## Shape

```
tip cam → YuNet + SFace → Presence{present,u,v,face_id}
                │
         ┌──────┴──────┐
         ▼             ▼
    present=false   present=true
         │             │
      Traverse       Follow
         └──────┬──────┘
                ▼
         arm.stream(q*)
```

## Traverse 扫描（安全 + 覆盖）

- 底座软限位扩到约 **±π**（固件 `constrain ±M_PI`），抬头到位后从**当前 yaw** 用 FOV 大步（≈0.55 rad/`toward_*_l`）扫，不先空跑去 −π。
- 扫描姿肘部收着（`q2≥2.2`），不把 tip 伸到桌面。
- **俯仰两行**：真抬头 `0.30/3.80`（el≈+25°）与近水平 `0.18/4.15`；端点换向才改俯仰。
- **跟随距离**：`span`（脸框相对宽度）≥0.28 时收肘/折肩拉开，目标舒适带约 0.20；≥0.40 优先后退再精对中。
- **跟随防丢**：近脸只用小步 yaw；短暂丢检后局部 `reacquire`；尖端相机左右/俯仰符号按实拍校正。
- 默认 settle≈0.35 s（presence），console spd≈280。

| op | 含义 |
|----|------|
| `find_any` | 遍历直到任意人脸 → 跟随；自动编号 |
| `find_id` | 遍历直到 `face#N` → 只跟该 id（需 `--face-id`） |
| `follow` | 只跟随画面中的人；**不扫掠**；可选 `--face-id` 过滤 |

```bash
python3 -m jev_servo run --op find_any --ticks 0
python3 -m jev_servo run --op find_id --face-id 3
python3 -m jev_servo run --op follow
python3 -m jev_servo console   # 下拉选 op，无 goal 文本框
```

`--goal` 仅留给 legacy `--mode jev`。

## Requirements

`REQ-PRESENCE-DETECT`, `REQ-PRESENCE-TRAVERSE`, `REQ-PRESENCE-FOLLOW`, `REQ-FACE-ID`
