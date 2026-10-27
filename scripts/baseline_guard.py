"""Freeze an accepted render set as a baseline, then catch regressions against it.

This is the answer to "fixed two, broke two": comparing each render to a known
good one catches the damage immediately instead of waiting for a human to notice.

    python baseline_guard.py save  --root <out_dir> --baseline <baseline_dir>
    python baseline_guard.py check --root <out_dir> --baseline <baseline_dir>

Thresholds are deliberately loose enough to absorb EEVEE's sampling noise
(measured: 0.002-0.006% of pixels differ between two identical runs) but tight
enough to catch a real regression (a body turning translucent or a face going
dark moves far more than that).

    python baseline_guard.py check ... --strict   # also fail on shape mismatch
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

VIEWS = ("front", "side", "back")
MAX_CHANGED = 0.02      # share of pixels allowed to differ
MIN_ALPHA_IOU = 0.99    # silhouette must stay essentially identical
MAX_MEAN_DELTA = 12.0   # mean channel difference over the whole image


def load_rgba(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA")).astype(np.float32)


def fingerprint(arr: np.ndarray) -> dict:
    alpha = arr[:, :, 3]
    solid = alpha >= 128
    rgb = arr[:, :, :3][solid] if solid.any() else np.zeros((1, 3))
    return {"alpha_px": int(solid.sum()),
            "mean_rgb": [round(float(v), 2) for v in rgb.mean(axis=0)],
            "size": [int(arr.shape[1]), int(arr.shape[0])]}


def compare(a: np.ndarray, b: np.ndarray) -> dict:
    if a.shape != b.shape:
        return {"ok": False, "reason": f"size {a.shape[1]}x{a.shape[0]} -> {b.shape[1]}x{b.shape[0]}"}
    ma, mb = a[:, :, 3] >= 128, b[:, :, 3] >= 128
    inter = np.logical_and(ma, mb).sum()
    union = np.logical_or(ma, mb).sum()
    iou = float(inter / union) if union else 1.0
    changed = float((np.abs(a[:, :, :3] - b[:, :, :3]).max(axis=2) > 8).mean())
    mean_delta = float(np.abs(a[:, :, :3] - b[:, :, :3]).mean())
    ok = iou >= MIN_ALPHA_IOU and changed <= MAX_CHANGED and mean_delta <= MAX_MEAN_DELTA
    return {"ok": ok, "alpha_iou": round(iou, 5), "changed": round(changed, 6),
            "mean_delta": round(mean_delta, 3)}


def cmd_save(root: Path, baseline: Path) -> int:
    if baseline.exists():
        print(f"[error] baseline already exists: {baseline}")
        print("        delete it yourself, or pass a different --baseline; refusing to overwrite")
        return 2
    manifest = {}
    count = 0
    for char_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        entry = {}
        for view in VIEWS:
            src = char_dir / f"{view}.png"
            if not src.is_file():
                print(f"[skip] {char_dir.name}/{view}.png missing")
                continue
            dst = baseline / char_dir.name / f"{view}.png"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)          # byte copy, no re-encode
            entry[view] = fingerprint(load_rgba(src))
            count += 1
        if entry:
            manifest[char_dir.name] = entry
    (baseline / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"[saved] {len(manifest)} characters / {count} views -> {baseline}")
    return 0


def cmd_check(root: Path, baseline: Path, strict: bool) -> int:
    mf = baseline / "manifest.json"
    if not mf.is_file():
        print(f"[error] no manifest in {baseline}; run `save` first")
        return 2
    manifest = json.loads(mf.read_text(encoding="utf8"))

    rows, bad = [], 0
    for name, entry in manifest.items():
        for view in VIEWS:
            if view not in entry:
                continue
            cur_path = root / name / f"{view}.png"
            ref_path = baseline / name / f"{view}.png"
            if not cur_path.is_file():
                rows.append({"char": name, "view": view, "status": "MISSING"})
                bad += 1
                continue
            r = compare(load_rgba(ref_path), load_rgba(cur_path))
            r.update({"char": name, "view": view})
            if not r["ok"]:
                bad += 1
                r["status"] = "REGRESSED"
            else:
                r["status"] = "ok"
            rows.append(r)

    print(f"{'character':<12}{'view':<7}{'status':<11}{'alpha IoU':>11}{'changed':>10}{'mean Δ':>9}")
    for r in rows:
        if r["status"] == "ok":
            print(f"{r['char']:<12}{r['view']:<7}{'ok':<11}{r['alpha_iou']:>11.5f}"
                  f"{r['changed'] * 100:>9.3f}%{r['mean_delta']:>9.2f}")
        elif r["status"] == "REGRESSED":
            print(f"{r['char']:<12}{r['view']:<7}{'REGRESSED':<11}{r['alpha_iou']:>11.5f}"
                  f"{r['changed'] * 100:>9.3f}%{r['mean_delta']:>9.2f}")
        else:
            print(f"{r['char']:<12}{r['view']:<7}{r['status']:<11}{r.get('reason', '')}")

    (root / "_baseline_diff.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"\n[summary] {len(rows) - bad}/{len(rows)} unchanged")
    if bad:
        print("[action] these views differ from the accepted baseline — inspect before delivering")
    return 0 if bad == 0 else (1 if strict else 0)


def main() -> int:
    ap = argparse.ArgumentParser(description="baseline guard for rendered view sets")
    ap.add_argument("action", choices=("save", "check"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--strict", action="store_true", help="check: non-zero exit on any regression")
    args = ap.parse_args()
    root, baseline = Path(args.root).resolve(), Path(args.baseline).resolve()
    if not root.is_dir():
        print(f"[error] --root is not a folder: {root}")
        return 2
    return cmd_save(root, baseline) if args.action == "save" else cmd_check(root, baseline, args.strict)


if __name__ == "__main__":
    sys.exit(main())
