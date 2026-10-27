"""Drive the three-view render for every character package in one folder.

One isolated Blender process per character, so a malformed PMX cannot poison the
rest. Paths travel through UTF-8 job files, never through the command line.

    python run_all.py --root <素材目录> --out <输出目录> --blender <blender可执行文件>

Exit code 0 only if every character rendered and passed the sanity check.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROP_WORDS = ("弓", "泡泡枪", "注射器", "药丸", "哑铃", "杯子", "钻地机",
              "书", "锤子", "剑", "刀", "枪", "棒", "伞", "弩", "法器")


def char_name(folder: Path) -> str:
    """Strip the packaging noise from a model folder name."""
    name = re.sub(r"_by_[^_]+_[0-9a-f]{16,}$", "", folder.name)
    name = name.replace("【", "").replace("】", "")
    name = re.sub(r"-(模之屋|模之屋版|官方)$", "", name)
    return name.split("_")[0].strip()


def pick_pmx(folder: Path, name: str):
    """Choose the character body, never a prop weapon/tool."""
    pmx = list(folder.rglob("*.pmx"))
    if not pmx:
        return None
    head = [p for p in pmx if p.stem.startswith(name) and len(p.stem) - len(name) <= 4]
    if head:
        return sorted(head, key=lambda p: (len(p.stem), -p.stat().st_size))[0]
    body = [p for p in pmx if not any(w in p.stem for w in PROP_WORDS)]
    pool = body or pmx
    return sorted(pool, key=lambda p: -p.stat().st_size)[0]


def verify_views(out_dir: Path):
    """Guard against the occasional all-transparent EEVEE render."""
    from PIL import Image
    import numpy as np

    detail = {}
    for key in ("front", "side", "back"):
        p = out_dir / f"{key}.png"
        if not p.is_file():
            return False, {key: "missing"}
        alpha = np.array(Image.open(p).convert("RGBA"))[:, :, 3]
        ys, xs = np.where(alpha >= 128)
        if len(ys) < 5000:
            return False, {key: f"blank ({len(ys)} opaque px)"}
        box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        if box[1] < 20 or box[3] > alpha.shape[0] - 20:
            return False, {key: f"touches frame {box}"}
        detail[key] = len(ys)
    return True, detail


def main() -> int:
    ap = argparse.ArgumentParser(description="render orthographic three-views for every PMX package")
    ap.add_argument("--root", required=True, help="folder containing one sub-folder per character")
    ap.add_argument("--out", required=True, help="output folder, one sub-folder per character")
    ap.add_argument("--blender", required=True, help="Blender executable (5.x with mmd_tools_local)")
    ap.add_argument("--render-script", default=None, help="defaults to render_three_views.py next to this file")
    ap.add_argument("--overrides", default=None, help="optional JSON with per-character overrides")
    ap.add_argument("--only", default=None, help="render a single character by name")
    ap.add_argument("--res", default="1600x2000", help="WxH, default 1600x2000")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--margin", type=float, default=1.12)
    ap.add_argument("--retries", type=int, default=1, help="extra attempts on a blank render")
    ap.add_argument("--jobs-dir", default=None, help="where job.json files go, defaults to <out>/_jobs")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    out_root = Path(args.out).expanduser().resolve()
    blender = Path(args.blender).expanduser().resolve()
    script = Path(args.render_script).resolve() if args.render_script else Path(__file__).with_name("render_three_views.py")
    jobs_dir = Path(args.jobs_dir).resolve() if args.jobs_dir else out_root / "_jobs"

    for label, path in (("--root", root), ("--blender", blender), ("--render-script", script)):
        if not path.exists():
            print(f"[error] {label} does not exist: {path}")
            return 2
    try:
        w, h = (int(v) for v in args.res.lower().split("x"))
    except ValueError:
        print("[error] --res must look like 1600x2000")
        return 2

    out_root.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)

    overrides = {}
    if args.overrides and Path(args.overrides).is_file():
        overrides = json.loads(Path(args.overrides).read_text(encoding="utf8"))

    jobs = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        name = char_name(folder)
        pmx = pick_pmx(folder, name)
        if pmx is None:
            print(f"[skip] {folder.name}: no .pmx found")
            continue
        job = {"name": name, "pmx": str(pmx), "out": str(out_root / name),
               "res": [w, h], "samples": args.samples, "margin": args.margin}
        ov = overrides.get(name, {})
        if ov.get("hide_materials"):
            job["hide_materials"] = ov["hide_materials"]
        jobs.append(job)

    if args.only:
        jobs = [j for j in jobs if j["name"] == args.only]
    if not jobs:
        print("[error] nothing to render")
        return 2

    print(f"[plan] {len(jobs)} character(s)")
    for j in jobs:
        print(f"   {j['name']:<8} <- {Path(j['pmx']).name}")

    results = []
    for idx, job in enumerate(jobs, 1):
        job_file = jobs_dir / f"{idx:02d}.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf8")
        log = job_file.with_suffix(".log")
        t0 = time.time()
        print(f"\n[{idx}/{len(jobs)}] {job['name']} ...", flush=True)
        ok, detail, rc = False, {}, None
        for attempt in range(args.retries + 1):
            with log.open("w", encoding="utf8", errors="replace") as fh:
                proc = subprocess.run(
                    [str(blender), "--background", "--python", str(script), "--", str(job_file)],
                    stdout=fh, stderr=subprocess.STDOUT, timeout=1800, cwd=str(blender.parent))
            rc = proc.returncode
            text = log.read_text(encoding="utf8", errors="replace")
            ran = rc == 0 and f"[done] {job['name']}" in text
            ok, detail = verify_views(Path(job["out"])) if ran else (False, {"returncode": rc})
            if ok:
                break
            if attempt < args.retries:
                print(f"    retry {attempt + 1} (previous attempt: {detail})", flush=True)
                time.sleep(2)
        dt = time.time() - t0
        pngs = sorted((Path(job["out"]).glob("*.png"))) if Path(job["out"]).is_dir() else []
        results.append({"name": job["name"], "ok": ok, "seconds": round(dt, 1),
                        "returncode": rc, "png": len(pngs), "detail": detail if not ok else "ok"})
        print(f"    ok={ok} rc={rc} {dt:.1f}s png={len(pngs)}", flush=True)
        if not ok:
            print(f"    ! {detail}", flush=True)

    (out_root / "_render_summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8")
    good = sum(1 for r in results if r["ok"])
    print(f"\n[summary] {good}/{len(results)} ok")
    return 0 if good == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
