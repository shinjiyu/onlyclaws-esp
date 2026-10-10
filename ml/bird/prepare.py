"""Turn the DCASE 2018 bird-audio-detection sets into device-exact features.

Each 10 s clip is resampled to 16 kHz and run through ms_frontend.tflite with
ml/tools/build/tflm_host (same TFLite Micro code as the firmware), giving
~499 rows x 40 int8 features per clip.

  python ml/bird/prepare.py --data /tmp/ocml/bird --out /tmp/ocml/bird/features.npz

Expects in --data: warblr.zip + warblr_meta.csv, ff1010.zip + ff1010_meta.csv
(archive.org warblrb10k_public / ff1010bird, figshare metadata 2018).
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from math import gcd
from pathlib import Path

import numpy as np
import scipy.io.wavfile as wavfile
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "ml" / "tools" / "build" / "tflm_host"
FRONTEND = ROOT / "ml" / "models" / "micro_speech" / "ms_frontend.tflite"
RATE = 16000
FEATURES = 40
SETS = {"warblr": "warblr", "ff1010": "ff1010"}


def to16k(raw: bytes) -> np.ndarray:
    sr, x = wavfile.read(io.BytesIO(raw))
    if x.dtype == np.int32:
        x = x / 65536.0
    elif x.dtype == np.uint8:
        x = (x.astype(np.float32) - 128.0) * 256.0
    elif np.issubdtype(x.dtype, np.floating):
        x = x * 32767.0
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if sr != RATE:
        g = gcd(sr, RATE)
        x = resample_poly(x, RATE // g, sr // g)
    return np.clip(np.round(x), -32768, 32767).astype("<i2")


def work(args: tuple[str, list[str], str]) -> list[tuple[str, int]]:
    """Decode a chunk of zip members to .s16, run the frontend, return (item, rows)."""
    zpath, members, tmp = args
    lines, out = [], []
    with zipfile.ZipFile(zpath) as z:
        for m in members:
            item = Path(m).stem
            pcm = Path(tmp) / f"{item}.s16"
            to16k(z.read(m)).tofile(pcm)
            lines.append(f"{pcm} {Path(tmp) / (item + '.i8')}")
            out.append(item)
    lst = Path(tmp) / f"list_{os.getpid()}_{out[0]}.txt"
    lst.write_text("\n".join(lines) + "\n")
    subprocess.run([str(HOST), "features", str(FRONTEND), str(lst)], check=True,
                   stderr=subprocess.DEVNULL)
    res = []
    for item in out:
        (Path(tmp) / f"{item}.s16").unlink()
        res.append((item, (Path(tmp) / f"{item}.i8").stat().st_size // FEATURES))
    lst.unlink()
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--limit", type=int, default=0, help="clips per set (0 = all)")
    a = ap.parse_args()

    feats, labels, sets, items = [], [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for name in SETS:
            meta = {r["itemid"]: int(r["hasbird"])
                    for r in csv.DictReader(open(a.data / f"{name}_meta.csv"))}
            zpath = str(a.data / f"{name}.zip")
            with zipfile.ZipFile(zpath) as z:
                members = [m for m in z.namelist()
                           if m.lower().endswith(".wav") and Path(m).stem in meta]
            if a.limit:
                members = members[: a.limit]
            chunks = [members[i : i + 100] for i in range(0, len(members), 100)]
            done = 0
            with ProcessPoolExecutor(a.jobs) as pool:
                for res in pool.map(work, [(zpath, c, tmp) for c in chunks]):
                    for item, n in res:
                        f = Path(tmp) / f"{item}.i8"
                        rows = np.fromfile(f, dtype=np.int8).reshape(n, FEATURES)
                        f.unlink()
                        feats.append(rows)
                        labels.append(meta[item])
                        sets.append(name)
                        items.append(item)
                    done += len(res)
                    print(f"{name}: {done}/{len(members)}", flush=True)

    n = max(len(f) for f in feats)
    x = np.full((len(feats), n, FEATURES), -128, dtype=np.int8)
    lens = np.array([len(f) for f in feats], dtype=np.int32)
    for i, f in enumerate(feats):
        x[i, : len(f)] = f
    np.savez_compressed(a.out, x=x, lens=lens, y=np.array(labels, dtype=np.int8),
                        set=np.array(sets), item=np.array(items))
    print(f"saved {a.out}: {x.shape}, birds {int(np.sum(labels))}/{len(labels)}")


if __name__ == "__main__":
    main()
