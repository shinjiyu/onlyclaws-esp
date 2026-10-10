"""CLI: python -m jev_servo run|console|mcp|map-demo|faces"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo.loop import run_loop  # noqa: E402
from jev_servo.interval import choice_to_interval  # noqa: E402
from jev_servo.mech import JOINTS  # noqa: E402
from jev_servo.ops import OPS, op_help  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OnlyClaws pathway C — presence ops / JEV")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="decision loop")
    run.add_argument(
        "--op",
        choices=list(OPS),
        default=None,
        help="finite op: " + "; ".join(f"{k}={v}" for k, v in op_help().items()),
    )
    run.add_argument(
        "--face-id",
        type=int,
        default=None,
        help="target gallery id (required for find_id; optional filter for follow)",
    )
    run.add_argument(
        "--goal",
        default=None,
        help="legacy free-text (JEV mode only); prefer --op for presence",
    )
    run.add_argument(
        "--ticks",
        type=int,
        default=3,
        help="number of ticks; 0 = until Ctrl-C",
    )
    run.add_argument(
        "--transport",
        choices=("usb", "cloud"),
        default="usb",
    )
    run.add_argument("--port", help="USB serial port (default: auto)")
    run.add_argument("--t-dec", type=float, default=0.0)
    run.add_argument("--spd", type=int, default=220)
    run.add_argument("--settle", type=float, default=None)
    run.add_argument("--feedback-every", type=int, default=None)
    run.add_argument("--stream-wait", type=float, default=18.0)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-arm", action="store_true")
    run.add_argument("--image", help="still image instead of live tip cam")
    run.add_argument("--scene", help="override scene state string")
    run.add_argument(
        "--mode",
        choices=("auto", "presence", "jev"),
        default="auto",
    )
    run.add_argument("--no-identify", action="store_true")
    run.add_argument("--gallery-dir", default=None)
    run.add_argument(
        "--log-dir",
        default=str(_ROOT / "jev_servo" / "runs" / "latest"),
    )

    demo = sub.add_parser("map-demo", help="print choice→interval for a sample q")
    demo.add_argument("--q", nargs=4, type=float, default=[-0.09, 0.35, 2.15, 3.90])

    cons = sub.add_parser("console", help="web Start/Stop console")
    cons.add_argument("--host", default="127.0.0.1")
    cons.add_argument("--http-port", type=int, default=8765)

    sub.add_parser("mcp", help="stdio MCP for Cursor (presence arm tools)")

    faces = sub.add_parser("faces", help="list / rename face gallery")
    faces.add_argument("--gallery-dir", default=None)
    faces_sub = faces.add_subparsers(dest="faces_cmd", required=True)
    faces_sub.add_parser("list")
    ren = faces_sub.add_parser("rename")
    ren.add_argument("face_id", type=int)
    ren.add_argument("name")

    args = ap.parse_args(argv)

    if args.cmd == "console":
        from jev_servo.console import serve

        serve(host=args.host, http_port=args.http_port)
        return 0

    if args.cmd == "mcp":
        from jev_servo.mcp_server import main as mcp_main

        mcp_main()
        return 0

    if args.cmd == "faces":
        from vision.identity import FaceGallery, sface_available

        gal = FaceGallery(args.gallery_dir)
        if args.faces_cmd == "list":
            print(
                json.dumps(
                    {
                        "path": str(gal.json_path),
                        "sface": sface_available(),
                        "faces": gal.list_faces(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.faces_cmd == "rename":
            rec = gal.rename(args.face_id, args.name)
            if rec is None:
                print(f"unknown face_id={args.face_id}", file=sys.stderr)
                return 1
            print(json.dumps(rec.as_dict(), ensure_ascii=False, indent=2))
            return 0
        return 1

    if args.cmd == "map-demo":
        for j, qj in zip(JOINTS, args.q):
            print(f"## {j.name} q={qj}")
            for ch in (
                "stay",
                "toward_neg_s",
                "toward_pos_s",
                "toward_neg_l",
                "toward_pos_l",
                "widen_stay",
            ):
                iv = choice_to_interval(ch, qj, j)
                print(f"  {ch:14s} -> [{iv.lo:.3f},{iv.hi:.3f}] mid={iv.mid:.3f}")
        return 0

    if args.cmd == "run":
        if not args.op and not args.goal:
            args.op = "find_any"
        if args.mode == "jev" and not args.goal:
            print("--mode jev requires --goal", file=sys.stderr)
            return 2
        ticks = run_loop(
            goal=args.goal,
            op=args.op,
            face_id=args.face_id,
            ticks=args.ticks,
            t_dec=args.t_dec,
            spd=args.spd,
            settle_s=args.settle,
            dry_run=args.dry_run,
            no_arm=args.no_arm,
            image=args.image,
            scene_override=args.scene,
            log_dir=args.log_dir,
            feedback_every=args.feedback_every,
            stream_wait_s=args.stream_wait,
            transport=args.transport,
            port=args.port,
            mode=args.mode,
            identify=not args.no_identify,
            gallery_dir=args.gallery_dir,
        )
        summary = [
            {
                "choices": t.choices,
                "moved": t.moved,
                "reached": t.reached,
                "q_star": t.q_star,
            }
            for t in ticks
        ]
        print("\nSUMMARY", json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
