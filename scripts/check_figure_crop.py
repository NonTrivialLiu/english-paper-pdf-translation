#!/usr/bin/env python3
"""核查交付图件与源页图框。清单留在任务工作区。

清单为 JSON 数组，或含 figures 数组的 JSON 对象。每项包含 figure、page、box、image；
页面渲染件填写 dpi 与 pad，原生嵌入位图填写 mode=native：
{"figure": 9, "page": 21, "box": [x0, y0, x1, y1],
 "image": "figures/fig9.png", "dpi": 300, "pad": 0}
图内文字与相邻正文的归属仍以源页和最终图件的并排查看裁决。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pymupdf
from PIL import Image


def caption_rects(page: pymupdf.Page) -> list[tuple[int, pymupdf.Rect]]:
    pattern = re.compile(r"^\s*fig(?:ure)?\.?\s*(\d+)(?:\s|[.:：])", re.IGNORECASE)
    captions: list[tuple[int, pymupdf.Rect]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        for index, line in enumerate(lines):
            title = "".join(span["text"] for span in line["spans"]).strip()
            match = pattern.match(title)
            if match:
                rect = pymupdf.Rect(line["bbox"])
                for continuation in lines[index + 1 :]:
                    rect |= pymupdf.Rect(continuation["bbox"])
                captions.append((int(match.group(1)), rect))
    return captions


def long_lines_in_box(page: pymupdf.Page, box: pymupdf.Rect) -> int:
    count = 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            content = "".join(span["text"] for span in line["spans"]).strip()
            if len(content) >= 60 and box.intersects(pymupdf.Rect(line["bbox"])):
                count += 1
    return count


def inspect_image(path: Path, box: pymupdf.Rect, dpi: float | None, pad: float,
                  edge_px: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    hints: list[str] = []
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        if dpi is not None:
            expected_w = (box.width + 2 * pad) * dpi / 72
            expected_h = (box.height + 2 * pad) * dpi / 72
            if abs(width - expected_w) > 5 or abs(height - expected_h) > 5:
                errors.append(
                    f"图件 {width}×{height}px 与所记图框/DPI "
                    f"{expected_w:.0f}×{expected_h:.0f}px 不一致"
                )
        ink = image.convert("L").point(lambda value: 255 if value < 180 else 0)
        bounds = ink.getbbox()
        if bounds is None:
            hints.append("图件缺少可识别的深色内容")
        else:
            margins = (bounds[0], bounds[1], width - bounds[2], height - bounds[3])
            if min(margins) < edge_px:
                hints.append(f"深色内容贴近图边：左/上/右/下={margins}px")
    return errors, hints


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--assets-root", type=Path,
                        help="图件相对路径的根目录；默认使用清单所在目录")
    parser.add_argument("--edge-px", type=int, default=4)
    args = parser.parse_args()

    records = json.loads(args.manifest.read_text(encoding="utf-8"))
    if isinstance(records, dict):
        records = records.get("figures")
    if not isinstance(records, list) or not records:
        parser.error("清单需要包含图件记录的 JSON 数组")
    root = args.assets_root or args.manifest.parent
    source = pymupdf.open(args.source_pdf)
    hard = review = 0
    for record in records:
        number = int(record["figure"])
        page_no = int(record["page"])
        image_path = root / record["image"]
        box = pymupdf.Rect(record["box"])
        errors: list[str] = []
        hints: list[str] = []
        if page_no < 1 or page_no > source.page_count:
            errors.append(f"源页 {page_no} 超出范围")
        elif box.is_empty or not source[page_no - 1].rect.contains(box):
            errors.append("图框超出源页或为空")
        else:
            page = source[page_no - 1]
            captions = caption_rects(page)
            if not any(found == number for found, _ in captions):
                hints.append("源页图注定位待核对")
            for found, caption in captions:
                if box.intersects(caption):
                    errors.append(
                        f"图框与图 {found} 图注文字框相交："
                        f"{tuple(round(v, 1) for v in caption)}"
                    )
            long_lines = long_lines_in_box(page, box)
            if long_lines:
                hints.append(f"框内有 {long_lines} 行长文本，核对其属于图内内容")
        if image_path.is_file():
            if record.get("mode") != "native" and record.get("dpi") is None:
                hints.append("页面渲染件的 DPI 待记录，像素尺寸待核对")
            image_errors, image_hints = inspect_image(
                image_path, box, record.get("dpi"), float(record.get("pad", 0)),
                args.edge_px,
            )
            errors.extend(image_errors)
            hints.extend(image_hints)
        else:
            errors.append(f"图件缺失：{image_path}")
        hard += bool(errors)
        review += bool(hints)
        print(f"图 {number}：{'处理' if errors else '复核' if hints else '通过'}")
        for item in errors:
            print(f"  差异：{item}")
        for item in hints:
            print(f"  提示：{item}")
    source.close()
    print(f"图件：{len(records)}；实质差异：{hard}；待目视复核：{review}")
    return 1 if hard else 2 if review else 0


if __name__ == "__main__":
    raise SystemExit(main())
