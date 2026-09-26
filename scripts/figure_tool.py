#!/usr/bin/env python3
"""网格定位、裁切与校验 PDF 原图（多篇通用）。

三类子命令：
  grid    渲染整页并叠加坐标网格，用于人工/多模态定位
  locate  由 pdftotext -bbox 的图注位置推算图框候选（PDF 点坐标）
  crop    按 PDF 点坐标裁切，输出高分辨率 PNG

源 PDF 通过全局参数 `--pdf` 指定，必须显式给出。
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

POINTS_PER_INCH = 72.0


def render_page(pdf: Path, page: int, dpi: int, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi),
            "-png", "-singlefile", str(pdf), str(out.with_suffix("")),
        ],
        check=True,
    )
    return out


def add_grid(path: Path, out: Path, major: int = 50, minor: int = 25) -> Path:
    image = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for x in range(0, width, minor):
        draw.line([(x, 0), (x, height)], fill=(255, 200, 200), width=1)
    for y in range(0, height, minor):
        draw.line([(0, y), (width, y)], fill=(200, 200, 255), width=1)
    for x in range(0, width, major):
        draw.line([(x, 0), (x, height)], fill=(200, 0, 0), width=1)
        draw.text((x + 2, 2), str(x), fill=(200, 0, 0))
    for y in range(0, height, major):
        draw.line([(0, y), (width, y)], fill=(0, 0, 200), width=1)
        draw.text((2, y + 2), str(y), fill=(0, 0, 200))
    image.save(out)
    return out


def page_boxes(bbox_html: Path) -> dict[int, list[tuple[float, float, float, float, str]]]:
    """把 pdftotext -bbox 输出整理成 {页号: [(x0, y0, x1, y1, 词)]}。"""

    text = bbox_html.read_text(encoding="utf-8")
    pages: dict[int, list[tuple[float, float, float, float, str]]] = {}
    for index, chunk in enumerate(text.split("<page ")[1:], start=1):
        words = re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',
            chunk,
        )
        pages[index] = [
            (float(a), float(b), float(c), float(d), w) for a, b, c, d, w in words
        ]
    return pages


def locate(bbox_html: Path) -> None:
    """按图注位置给出候选图框：图注上方的空白块即图本体。"""

    pages = page_boxes(bbox_html)
    for page, words in pages.items():
        if not words:
            continue
        rows: dict[int, list[tuple[float, float, float, float, str]]] = {}
        for word in words:
            rows.setdefault(round(word[1]), []).append(word)
        ordered = [rows[key] for key in sorted(rows)]
        for index, row in enumerate(ordered):
            text = " ".join(item[4] for item in row)
            match = re.match(r"Figure\s?(\d+)[:.]", text)
            if not match:
                continue
            caption_top = min(item[1] for item in row)
            x0 = min(item[0] for item in row)
            x1 = max(item[2] for item in row)
            previous_bottom = 0.0
            for earlier in reversed(ordered[:index]):
                top = min(item[1] for item in earlier)
                if top < caption_top - 8:
                    previous_bottom = max(item[3] for item in earlier)
                    break
            print(
                f"page {page}  Figure {match.group(1)}  "
                f"caption_y={caption_top:.0f}  block_y=[{previous_bottom:.0f},{caption_top:.0f}]  "
                f"x=[{x0:.0f},{x1:.0f}]"
            )


def crop(pdf: Path, page: int, box: list[float], dpi: int, out: Path, pad: float) -> Path:
    """按 PDF 点坐标裁切；先按目标分辨率整页渲染，再换算像素。"""

    raw = out.with_name(out.stem + "_page").with_suffix(".png")
    render_page(pdf, page, dpi, raw)
    scale = dpi / POINTS_PER_INCH
    image = Image.open(raw)
    x0, y0, x1, y1 = box
    pixels = (
        max(0, int((x0 - pad) * scale)),
        max(0, int((y0 - pad) * scale)),
        min(image.width, int((x1 + pad) * scale)),
        min(image.height, int((y1 + pad) * scale)),
    )
    image.crop(pixels).save(out)
    raw.unlink()
    print(f"{out}  size={Image.open(out).size}  page={page}  points={box}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True, help="源 PDF 路径")
    sub = parser.add_subparsers(dest="command", required=True)

    grid = sub.add_parser("grid")
    grid.add_argument("--page", type=int, required=True)
    grid.add_argument("--dpi", type=int, default=150)
    grid.add_argument("--out", type=Path, required=True)

    locate_parser = sub.add_parser("locate")
    locate_parser.add_argument("--bbox", type=Path, required=True)

    crop_parser = sub.add_parser("crop")
    crop_parser.add_argument("--page", type=int, required=True)
    crop_parser.add_argument("--box", type=float, nargs=4, required=True)
    crop_parser.add_argument("--dpi", type=int, default=400)
    crop_parser.add_argument("--pad", type=float, default=2.0)
    crop_parser.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "grid":
        raw = render_page(
            args.pdf, args.page, args.dpi, args.out.with_name(args.out.stem + "_raw.png")
        )
        add_grid(raw, args.out)
        raw.unlink()
        print(f"{args.out}  dpi={args.dpi}  size={Image.open(args.out).size}")
    elif args.command == "locate":
        locate(args.bbox)
    else:
        crop(args.pdf, args.page, args.box, args.dpi, args.out, args.pad)


if __name__ == "__main__":
    main()
