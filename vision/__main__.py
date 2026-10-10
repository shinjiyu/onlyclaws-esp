"""CLI: python -m vision path/to.jpg [--json]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m vision` from repo root or vision/
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vision.pipeline import describe_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OnlyClaws vision pathway: frame → objects + empties")
    ap.add_argument("image", help="image path")
    ap.add_argument("--json", action="store_true", help="print full JSON")
    ap.add_argument("--no-faces", action="store_true")
    ap.add_argument("--no-coco", action="store_true", help="disable YOLOv8n COCO detector")
    ap.add_argument("--blobs", action="store_true", help="force saliency blobs (also used if no COCO model)")
    ap.add_argument("--conf", type=float, default=0.35, help="COCO confidence")
    args = ap.parse_args(argv)

    desc = describe_path(
        args.image,
        faces=not args.no_faces,
        coco=False if args.no_coco else None,
        blobs=True if args.blobs else None,
        coco_conf=args.conf,
    )
    if args.json:
        print(json.dumps(desc.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"# {desc.width}x{desc.height}  {desc.ms:.1f} ms")
        print(desc.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
