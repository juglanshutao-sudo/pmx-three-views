"""Compose one three-view sheet per character, plus a contact sheet.

Panels are pasted at 1:1 with no cropping, so the three silhouettes stay directly
comparable. Refuses to build a sheet whose silhouette touches the frame edge.

    python assemble_sheets.py --root <三视图输出目录> [--only <角色名>]
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PANEL_W, PANEL_H = 1600, 2000
VIEWS = [("front", "正面", "FRONT"), ("side", "侧面", "SIDE"), ("back", "背面", "BACK")]
GAP, PAD_L, HEADER, FOOTER = 60, 60, 210, 190
ACCENT, INK, SUB, RULE = "#2F6BD8", "#23272E", "#7A828C", "#DCE0E5"


def font(path, size):
    return ImageFont.truetype(path, size)


def clean_alpha(im: Image.Image) -> Image.Image:
    """Drop the few sub-8/255 pixels EEVEE leaves on the frame edge."""
    import numpy as np
    arr = np.array(im.convert("RGBA"))
    arr[:, :, 3][arr[:, :, 3] < 8] = 0
    return Image.fromarray(arr, "RGBA")


def content_box(im: Image.Image):
    import numpy as np
    alpha = np.array(im.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(alpha >= 128)
    if len(ys) == 0:
        raise RuntimeError("empty render")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def build_one(root: Path, name: str, report: dict, fonts) -> dict:
    src = root / name
    missing = [k for k, _, _ in VIEWS if not (src / f"{k}.png").is_file()]
    if missing:
        raise RuntimeError(f"missing views: {missing}")

    sheet_w = PAD_L * 2 + PANEL_W * 3 + GAP * 2
    sheet_h = HEADER + PANEL_H + FOOTER
    sheet = Image.new("RGB", (sheet_w, sheet_h), "white")
    d = ImageDraw.Draw(sheet)
    regular, bold = fonts

    d.rectangle((0, 0, sheet_w, 8), fill=ACCENT)
    d.text((PAD_L, 58), f"{name} · 三视图", font=font(bold, 74), fill=INK)
    d.text((sheet_w - PAD_L, 96), "正交投影 / 同比例 1:1 / 原始贴图配色",
           anchor="rs", font=font(regular, 32), fill=SUB)
    d.line((PAD_L, HEADER - 34, sheet_w - PAD_L, HEADER - 34), fill=RULE, width=2)

    panels = []
    for i, (key, label, english) in enumerate(VIEWS):
        x = PAD_L + i * (PANEL_W + GAP)
        y = HEADER
        with Image.open(src / f"{key}.png") as raw:
            im = clean_alpha(raw)
            if im.size != (PANEL_W, PANEL_H):
                raise RuntimeError(f"{key}: unexpected size {im.size}, expected {PANEL_W}x{PANEL_H}")
            box = content_box(im)
            if box[0] < 8 or box[1] < 20 or box[2] > PANEL_W - 8 or box[3] > PANEL_H - 20:
                raise RuntimeError(f"{key}: silhouette touches the frame edge {box}")
            sheet.paste(im, (x, y), im)
            panels.append({"view": key, "content_bbox": list(box)})
        cx = x + PANEL_W // 2
        d.text((cx, HEADER + PANEL_H + 44), label, anchor="ma", font=font(bold, 46), fill=INK)
        d.text((cx, HEADER + PANEL_H + 100), english, anchor="ma", font=font(regular, 24), fill=SUB)

    size = report.get("bounds", {}).get("size", [0, 0, 0])
    d.line((PAD_L, sheet_h - 62, sheet_w - PAD_L, sheet_h - 62), fill=RULE, width=2)
    d.text((PAD_L, sheet_h - 46), "依据提供 3D 模型直接正交渲染（原始 A-pose）",
           font=font(regular, 24), fill=SUB)
    if any(size):
        d.text((sheet_w - PAD_L, sheet_h - 46),
               f"包络 {size[2]:.3f}H x {size[0]:.3f}W x {size[1]:.3f}D / 分辨率 {PANEL_W}x{PANEL_H}",
               anchor="ra", font=font(regular, 24), fill=SUB)

    target = src / f"{name}_三视图.png"
    sheet.save(target, dpi=(300, 300))
    sheet.resize((sheet_w // 3, sheet_h // 3), Image.Resampling.LANCZOS).save(src / "_预览.png")
    return {"name": name, "sheet": str(target), "size": [sheet_w, sheet_h],
            "panels": panels, "ortho_scale": report.get("ortho_scale")}


def build_contact(root: Path, names, fonts) -> str:
    cols, cell_w, cell_h = 6, 320, 460
    rows = (len(names) + cols - 1) // cols
    cw = PAD_L * 2 + cols * cell_w + (cols - 1) * 24
    ch = HEADER + rows * cell_h + 110
    sheet = Image.new("RGB", (cw, ch), "white")
    d = ImageDraw.Draw(sheet)
    regular, bold = fonts

    d.rectangle((0, 0, cw, 8), fill=ACCENT)
    d.text((PAD_L, 56), "角色 · 三视图总览", font=font(bold, 66), fill=INK)
    d.text((cw - PAD_L, 92), f"{len(names)} 个角色 / 正交投影 / 高度归一化",
           anchor="rs", font=font(regular, 30), fill=SUB)
    d.line((PAD_L, HEADER - 30, cw - PAD_L, HEADER - 30), fill=RULE, width=2)

    for i, name in enumerate(names):
        r, c = divmod(i, cols)
        x = PAD_L + c * (cell_w + 24)
        y = HEADER + r * cell_h
        with Image.open(root / name / "front.png") as raw:
            im = clean_alpha(raw)
            im = im.crop(content_box(im))
            k = min(cell_w / im.width, (cell_h - 56) / im.height)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                           Image.Resampling.LANCZOS)
            sheet.paste(im, (x + (cell_w - im.width) // 2, y + (cell_h - 56 - im.height)), im)
        d.text((x + cell_w // 2, y + cell_h - 34), name, anchor="ma", font=font(bold, 30), fill=INK)

    d.text((PAD_L, ch - 56), "全部由 PMX 模型直接正交渲染导出（各角色按自身高度归一化显示）",
           font=font(regular, 22), fill=SUB)
    target = root / "_总览_全部角色正视图.png"
    sheet.save(target, dpi=(300, 300))
    return str(target)


def main():
    ap = argparse.ArgumentParser(description="compose three-view sheets")
    ap.add_argument("--root", required=True, help="folder produced by run_all.py")
    ap.add_argument("--only", default=None)
    ap.add_argument("--font", default="msyh.ttc", help="regular font file name or path")
    ap.add_argument("--font-bold", default="msyhbd.ttc", help="bold font file name or path")
    ap.add_argument("--font-dir", default=None, help="folder holding the fonts, e.g. a Windows Fonts dir")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"[error] --root is not a folder: {root}")
        return 2

    def resolve(name):
        p = Path(name)
        if p.is_file():
            return str(p)
        if args.font_dir:
            cand = Path(args.font_dir) / name
            if cand.is_file():
                return str(cand)
        print(f"[warn] font not found: {name}; falling back to the PIL default (labels will be tiny)")
        return None

    regular, bold = resolve(args.font), resolve(args.font_bold)
    fonts = (regular or bold, bold or regular)
    if fonts[0] is None:
        print("[error] need at least one usable font file; pass --font / --font-dir")
        return 2

    names = sorted(p.name for p in root.iterdir()
                   if p.is_dir() and (p / "_render_report.json").is_file())
    if args.only:
        names = [n for n in names if n == args.only]
    if not names:
        print("[error] no rendered characters found (missing _render_report.json)")
        return 2

    built = []
    for name in names:
        report = json.loads((root / name / "_render_report.json").read_text(encoding="utf8"))
        try:
            built.append(build_one(root, name, report, fonts))
            print(f"[sheet] {name} ok")
        except Exception as exc:
            print(f"[sheet] {name} FAILED: {exc}")

    if len(names) > 1:
        print("[contact]", build_contact(root, [b["name"] for b in built], fonts))

    (root / "_sheet_report.json").write_text(
        json.dumps(built, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"[summary] {len(built)}/{len(names)} sheets")
    return 0 if len(built) == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
