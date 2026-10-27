"""Sanity gate for the three-view renders.

Automatic colour grading does NOT work here. These are unlit renders, so every
surface is a flat tone and any "looks too dark" heuristic lights up legitimate
dark clothing — measured 20 of 36 views false-positive across a dozen characters.

So this only hard-fails on what a script can actually judge:

    * missing / empty render
    * silhouette touching the frame edge

A flat-dark tile share is printed as INFO for a human to eyeball against the
contact sheet. Colour correctness must be confirmed by looking at the images.

    python check_views.py --root <三视图输出目录>
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

TILE = 32
DARK_LUM = 55
MAX_TILE_STD = 12.0
MIN_OPAQUE = 5000


def analyse(path: Path):
    arr = np.array(Image.open(path).convert("RGBA"))
    h, w = arr.shape[:2]
    solid = arr[:, :, 3] >= 128
    opaque = int(solid.sum())
    if opaque < MIN_OPAQUE:
        return {"status": "empty", "opaque_px": opaque}

    ys, xs = np.where(solid)
    box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    if box[1] < 20 or box[3] > h - 20:
        return {"status": "touches-frame", "opaque_px": opaque, "bbox": box}

    lum = arr[:, :, :3].astype(np.float32).mean(axis=2)
    tiles = suspect = 0
    for y in range(0, h - TILE + 1, TILE):
        for x in range(0, w - TILE + 1, TILE):
            a = solid[y:y + TILE, x:x + TILE]
            if a.mean() < 0.5:
                continue
            tiles += 1
            l = lum[y:y + TILE, x:x + TILE][a]
            if l.size and (l < DARK_LUM).mean() > 0.92 and l.std() < MAX_TILE_STD:
                suspect += 1
    return {"status": "ok", "opaque_px": opaque, "bbox": box, "tiles": tiles,
            "flat_dark_tiles": suspect,
            "flat_dark_ratio": round(suspect / max(tiles, 1), 4)}


def main():
    ap = argparse.ArgumentParser(description="sanity-check rendered three-views")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"[error] --root is not a folder: {root}")
        return 2

    rows, bad = [], 0
    for char_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for view in ("front", "side", "back"):
            p = char_dir / f"{view}.png"
            if not p.is_file():
                rows.append({"char": char_dir.name, "view": view, "status": "missing"})
                bad += 1
                continue
            r = analyse(p)
            r.update({"char": char_dir.name, "view": view})
            if r["status"] != "ok":
                bad += 1
            rows.append(r)

    print(f"{'character':<12}{'view':<8}{'status':<14}{'opaque px':>10}{'flat dark':>11}{'ratio':>8}")
    for r in rows:
        if r["status"] == "ok":
            print(f"{r['char']:<12}{r['view']:<8}{'OK':<14}{r['opaque_px']:>10}"
                  f"{r['flat_dark_tiles']:>11}{r['flat_dark_ratio'] * 100:>7.1f}%")
        else:
            print(f"{r['char']:<12}{r['view']:<8}{r['status']:<14}{r.get('opaque_px', '-'):>10}")

    (root / "_qa_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"\n[hard-fail] {bad}/{len(rows)}  (flat-dark ratio is INFO only, confirm colours by eye)")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
