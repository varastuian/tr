"""CLI: build / inspect ORB feature map from a folder of ordered images."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from uav_route.feature_map.library import FeatureMapLibrary


def _ingest(args: argparse.Namespace) -> None:
    src = Path(args.images_dir)
    out = Path(args.out_dir)
    exts = {".jpg", ".jpeg", ".png", ".bmp"}
    files = sorted(
        [p for p in src.iterdir() if p.suffix.lower() in exts],
        key=lambda p: p.name,
    )
    if not files:
        raise SystemExit(f"No images in {src}")

    lib = FeatureMapLibrary(out)
    for i, p in enumerate(files):
        bgr = cv2.imread(str(p))
        if bgr is None:
            print(f"skip unreadable {p}")
            continue
        if args.max_side > 0:
            h, w = bgr.shape[:2]
            m = max(h, w)
            if m > args.max_side:
                s = args.max_side / m
                bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        lib.add_image(bgr, meta={"path": str(p), "seq": i})
        print(f"keyframe {len(lib)-1} <- {p.name}", flush=True)
    lib.save()
    print(f"Saved {len(lib)} keyframes to {out}", flush=True)


def _query(args: argparse.Namespace) -> None:
    lib = FeatureMapLibrary.load(Path(args.map_dir))
    q = Path(args.image)
    bgr = cv2.imread(str(q))
    if bgr is None:
        raise SystemExit(f"Could not read {q}")
    hint = lib.suggest_toward_home(bgr, min_matches=args.min_matches, step=args.step)
    print(hint)


def main() -> None:
    p = argparse.ArgumentParser(description="uav-route ORB feature map (teach / repeat hint)")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("ingest", help="Build library from sorted images")
    i.add_argument("images_dir", type=Path)
    i.add_argument("--out-dir", type=Path, required=True)
    i.add_argument("--max-side", type=int, default=960, help="Resize so max(width,height) <= this (0=off)")
    i.set_defaults(func=_ingest)

    q = sub.add_parser("query", help="Query single image against saved map")
    q.add_argument("map_dir", type=Path)
    q.add_argument("image", type=Path)
    q.add_argument("--min-matches", type=int, default=25)
    q.add_argument("--step", type=int, default=3)
    q.set_defaults(func=_query)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
