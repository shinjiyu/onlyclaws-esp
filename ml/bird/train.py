"""Train the bird / no-bird classifier on features from prepare.py and export
an int8 .tflite that runs after ms_frontend on the device (ml.listen).

The frontend emits raw int8 bytes q; like micro_speech, the classifier reads
them as (q + 128) * IN_SCALE. Training uses the same mapping and the export
asserts the converted input quantization matches, because the firmware
copies frontend bytes straight into the classifier input.

Labels are per 10 s clip ("a bird somewhere in it"); windows are random
crops of `--frames` rows, so positives are noisy. Clip-level scores average
the window probabilities, as a Lua script polling ml.listen would.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
import ml_registry  # noqa: E402

IN_SCALE = 0.10171568393707275
IN_ZP = -128
WARMUP = 25  # rows skipped at clip start while frontend noise/PCAN state settles
FEATURES = 40


def to_float(q: np.ndarray) -> np.ndarray:
    return (q.astype(np.float32) - IN_ZP) * IN_SCALE


def split(clips: np.ndarray, y: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    uniq = np.unique(clips)
    rng.shuffle(uniq)
    n = len(uniq)
    val, test = set(uniq[: n // 10]), set(uniq[n // 10 : n // 5])
    tr = np.array([c not in val and c not in test for c in clips])
    va = np.array([c in val for c in clips])
    te = np.array([c in test for c in clips])
    return tr, va, te


def build(frames: int, width: int) -> tf.keras.Model:
    L = tf.keras.layers
    inp = L.Input((frames, FEATURES), name="features")
    x = L.Reshape((frames, FEATURES, 1))(inp)
    x = L.Conv2D(width, (5, 5), strides=(2, 2), padding="same", use_bias=False)(x)
    x = L.BatchNormalization()(x)
    x = L.ReLU()(x)
    for ch in (2 * width, 4 * width, 4 * width):
        x = L.DepthwiseConv2D((3, 3), strides=(2, 2), padding="same", use_bias=False)(x)
        x = L.BatchNormalization()(x)
        x = L.ReLU()(x)
        x = L.Conv2D(ch, (1, 1), use_bias=False)(x)
        x = L.BatchNormalization()(x)
        x = L.ReLU()(x)
    x = L.GlobalAveragePooling2D()(x)
    x = L.Dropout(0.3)(x)
    out = L.Dense(2, activation="softmax")(x)
    return tf.keras.Model(inp, out)


def crops(x: np.ndarray, y: np.ndarray, frames: int, batch: int, rng: np.random.Generator):
    rows = x.shape[1]
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    while True:
        # Balanced batches: warblr is ~75% bird, ff1010 ~25%.
        idx = np.concatenate([rng.choice(pos, batch // 2), rng.choice(neg, batch - batch // 2)])
        start = rng.integers(WARMUP, rows - frames + 1, batch)
        xb = np.stack([x[i, s : s + frames] for i, s in zip(idx, start)])
        xb = to_float(xb)
        # Light SpecAugment: one time mask and one frequency mask per example.
        for b in range(batch):
            t0, tw = rng.integers(0, frames), rng.integers(0, frames // 8)
            f0, fw = rng.integers(0, FEATURES), rng.integers(0, 6)
            xb[b, t0 : t0 + tw] = 0
            xb[b, :, f0 : f0 + fw] = 0
        yield xb, y[idx]


def windows(x: np.ndarray, frames: int, hop: int) -> np.ndarray:
    starts = range(WARMUP, x.shape[1] - frames + 1, hop)
    return np.stack([x[:, s : s + frames] for s in starts], axis=1)  # [N, W, F, 40]


def clip_scores(model: tf.keras.Model, x: np.ndarray, frames: int, hop: int) -> np.ndarray:
    w = windows(x, frames, hop)
    n, k = w.shape[:2]
    p = model.predict(to_float(w.reshape(n * k, frames, FEATURES)), batch_size=512, verbose=0)
    return p[:, 1].reshape(n, k).mean(axis=1)


def auc(y: np.ndarray, s: np.ndarray) -> float:
    order = np.argsort(s)
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def export(model: tf.keras.Model, xtr: np.ndarray, frames: int, out: Path) -> bytes:
    rng = np.random.default_rng(1)

    def rep():
        lo = np.zeros((1, frames, FEATURES), np.float32)
        yield [lo]
        yield [lo + 255 * IN_SCALE]
        for _ in range(300):
            i, s = rng.integers(len(xtr)), rng.integers(WARMUP, xtr.shape[1] - frames + 1)
            yield [to_float(xtr[i : i + 1, s : s + frames])]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    blob = conv.convert()
    interp = tf.lite.Interpreter(model_content=blob)
    scale, zp = interp.get_input_details()[0]["quantization"]
    if abs(scale - IN_SCALE) > 1e-6 or zp != IN_ZP:
        raise SystemExit(f"input quantization {scale},{zp} != frontend {IN_SCALE},{IN_ZP}")
    ml_registry.check_opset(blob)
    out.write_bytes(blob)
    return blob


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("/tmp/ocml/bird"))
    ap.add_argument("--out", type=Path, default=ROOT / "ml" / "models" / "bird_detect")
    ap.add_argument("--frames", type=int, default=149)
    ap.add_argument("--width", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    tf.keras.utils.set_random_seed(args.seed)

    d = np.load(args.data / "features.npz")
    keep = d["lens"] >= 450  # drop the few clips well short of 10 s
    rows = int(d["lens"][keep].min())
    x, y, ds = d["x"][keep, :rows], d["y"][keep].astype(np.int32), d["set"][keep]
    clips = np.arange(len(y))
    tr, va, te = split(clips, y, args.seed)
    print(f"train {tr.sum()} val {va.sum()} test {te.sum()} windows of {args.frames} rows; pos {y.mean():.2f}")

    model = build(args.frames, args.width)
    model.summary(print_fn=lambda s: None)
    print(f"params {model.count_params()}")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(tf.keras.optimizers.schedules.CosineDecay(2e-3, args.epochs * args.steps)),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    rng = np.random.default_rng(args.seed)
    best, best_w = -1.0, None
    for epoch in range(args.epochs):
        model.fit(
            crops(x[tr], y[tr], args.frames, 64, rng),
            steps_per_epoch=args.steps,
            epochs=1,
            verbose=0,
        )
        a = auc(y[va], clip_scores(model, x[va], args.frames, 50))
        print(f"epoch {epoch + 1}: val clip AUC {a:.3f}", flush=True)
        if a > best:
            best, best_w = a, model.get_weights()
    model.set_weights(best_w)

    report = {"frames": args.frames, "params": model.count_params(), "val_auc": round(best, 4)}
    s = clip_scores(model, x[te], args.frames, 50)
    report["test_auc"] = round(auc(y[te], s), 4)
    report["test_acc@0.5"] = round(float(((s > 0.5) == (y[te] == 1)).mean()), 4)
    for dname in np.unique(ds):
        m = ds[te] == dname
        report[f"test_auc_{dname}"] = round(auc(y[te][m], s[m]), 4)
    print(json.dumps(report, indent=1))

    args.out.mkdir(parents=True, exist_ok=True)
    blob = export(model, x[tr], args.frames, args.out / "bird_detect.tflite")
    meta = {
        "name": "bird_detect",
        "kind": "audio",
        "arena_kb": 64,
        "labels": ["no_bird", "bird"],
        "audio": {"rate": 16000, "window_ms": 30, "stride_ms": 20, "frames": args.frames,
                  "features": FEATURES, "frontend": "ms_frontend"},
    }
    (args.out / "bird_detect.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (args.out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    np.save(args.data / "test_items.npy", d["item"][keep][te])
    print(f"bird_detect.tflite {len(blob)} bytes")


if __name__ == "__main__":
    main()
