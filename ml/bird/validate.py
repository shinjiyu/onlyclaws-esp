"""Score the held-out test clips with the int8 bird_detect.tflite on the host.

Runs each clip through ml/tools/build/tflm_host classify (the firmware's TFLite
Micro code: ms_frontend + classifier), averages the per-window bird score and
reports clip-level AUC / accuracy, so the number matches what the device does.

  python ml/bird/validate.py --data /tmp/ocml/bird
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from prepare import FRONTEND, HOST, ROOT, SETS, to16k

MODEL = ROOT / "ml" / "models" / "bird_detect" / "bird_detect.tflite"


def auc(y: np.ndarray, s: np.ndarray) -> float:
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def work(args: tuple[str, list[str], str, str, int, int]) -> list[tuple[str, float]]:
    zpath, members, tmp, model, frames, hop = args
    out = []
    with zipfile.ZipFile(zpath) as z:
        for m in members:
            pcm = Path(tmp) / f"{Path(m).stem}.s16"
            to16k(z.read(m)).tofile(pcm)
            r = subprocess.run([str(HOST), "classify", str(FRONTEND), model, str(frames),
                                str(hop), str(pcm)], check=True, capture_output=True, text=True)
            pcm.unlink()
            bird = [float(l.split()[1]) for l in r.stdout.splitlines() if l.strip()]
            out.append((Path(m).stem, float(np.mean(bird)) if bird else 0.0))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--model", type=Path, default=MODEL)
    ap.add_argument("--hop", type=int, default=50)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    meta = json.loads(a.model.with_suffix(".meta.json").read_text())
    frames = meta["audio"]["frames"]
    test = set(np.load(a.data / "test_items.npy").tolist())
    labels, sets, jobs = {}, {}, []
    with tempfile.TemporaryDirectory() as tmp:
        for name in SETS:
            for r in csv.DictReader(open(a.data / f"{name}_meta.csv")):
                if r["itemid"] in test:
                    labels[r["itemid"]], sets[r["itemid"]] = int(r["hasbird"]), name
            zpath = str(a.data / f"{name}.zip")
            with zipfile.ZipFile(zpath) as z:
                members = [m for m in z.namelist()
                           if m.lower().endswith(".wav") and Path(m).stem in test]
            jobs += [(zpath, members[i : i + 20], tmp, str(a.model), frames, a.hop)
                     for i in range(0, len(members), 20)]
        scores = {}
        with ProcessPoolExecutor(a.jobs) as pool:
            for res in pool.map(work, jobs):
                scores.update(res)
                print(f"scored {len(scores)}/{len(test)}", flush=True)

    items = sorted(scores)
    y = np.array([labels[i] for i in items])
    s = np.array([scores[i] for i in items])
    ds = np.array([sets[i] for i in items])
    report = {"clips": len(items), "int8_auc": round(auc(y, s), 4),
              "int8_acc@0.5": round(float(((s >= 0.5) == y).mean()), 4)}
    for name in SETS:
        k = ds == name
        report[f"int8_auc_{name}"] = round(auc(y[k], s[k]), 4)
    print(json.dumps(report, indent=1))
    rp = a.model.parent / "report.json"
    rp.write_text(json.dumps({**json.loads(rp.read_text()), **report}, indent=1) + "\n")


if __name__ == "__main__":
    main()
