#!/usr/bin/env python3
"""从 PDF 内容流精确计算图框（替代"网格 + 肉眼"定位）。

思路与 pdffigures2 一类工具一致：图注文本作为锚点，图形对象（矢量绘制 + 位图放置框）
按竖直邻近关系聚合成块，取并集得到图框。输出为 PDF 点坐标，可直接交给裁切工具。

子命令：
  list    列出每页图注与推算出的图框
  mark    在页面渲染图上画出图框，用于人工复核
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

CAPTION_PREFIXES = ("Fig.", "Fig", "Figure", "FIGURE", "TABLE", "Table")
VERTICAL_GAP = 14.0   # 同一图块内相邻图形的最大竖直间隙（pt）
CAPTION_GAP = 14.0    # 图块底边与图注顶边的最大间距（pt）
HEADER_ZONE = 0.075   # 页眉区占比：落在该区域内的图形视为页面家具
PAD = 4.0             # 最终图框外扩余量（pt），用于容纳贴边的文字标签


def graphics_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """页面内图形对象的包围盒；整页级别的裁剪矩形单独剔除。"""

    rects: list[pymupdf.Rect] = []
    for drawing in page.get_drawings():
        rect = pymupdf.Rect(drawing["rect"])
        if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
            continue
        # 页面家具（页眉页脚横线、页级裁剪框）往往横跨整页，按宽度剔除。
        if rect.width > page.rect.width * 0.88:
            continue
        if rect.width > page.rect.width * 0.95 and rect.height > page.rect.height * 0.5:
            continue
        rect = rect & page.rect
        if rect.is_empty or rect.get_area() <= 4:
            continue
        if rect.y1 < page.rect.height * HEADER_ZONE:
            continue
        rects.append(rect)
    for image in page.get_images(full=True):
        for rect in page.get_image_rects(image[0]):
            if not rect.is_empty:
                clamped = pymupdf.Rect(rect) & page.rect
                if not clamped.is_empty:
                    rects.append(clamped)
    return rects


def text_lines(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    """逐行取文本及其包围盒：图注常常不是独立文本块，必须按行找。"""

    lines: list[tuple[pymupdf.Rect, str]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                lines.append((pymupdf.Rect(line["bbox"]), text))
    return lines


def captions(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    """图注行：编号后紧跟冒号或者句点，借此排除正文里的交叉引用。"""

    pattern = re.compile(r"^(Fig\.?|Figure|TABLE|Table)\s*([0-9]+|[IVX]+)\s*[.:]")
    return [
        (rect, text[:70])
        for rect, text in text_lines(page)
        if text.startswith(CAPTION_PREFIXES) and pattern.match(text)
    ]


def drop_containers(rects: list[pymupdf.Rect]) -> list[pymupdf.Rect]:
    """剔除"容器"矩形：图面上常有一条覆盖整图的背景/裁剪框，它比可见内容更宽，
    直接参与并集会把图框撑大。判据是它完整包含若干其它对象。"""

    keep: list[pymupdf.Rect] = []
    for index, rect in enumerate(rects):
        contained = sum(
            1
            for other_index, other in enumerate(rects)
            if other_index != index and rect.contains(other)
        )
        if contained >= 3:
            continue
        keep.append(rect)
    return keep


def figure_box(
    page: pymupdf.Page,
    caption: pymupdf.Rect,
    rects: list[pymupdf.Rect],
    lines: list[tuple[pymupdf.Rect, str]],
) -> pymupdf.Rect | None:
    """图注上方的图形对象按竖直邻近聚成块，再用图内文本标签补全边界。

    注意点：图形里常有一条覆盖整图的裁剪矩形，它的下沿会压过图注；因此先按图注
    顶边裁掉下沿，再参与聚类，而不是直接把越过图注的矩形丢掉。
    """

    limit = caption.y0 - 2.0
    # 带宽要比图注本身宽出足够余量：输出标签常常恰好落在图注右边界的延长线上。
    band_lo = caption.x0 - 80.0
    band_hi = caption.x1 + 80.0
    clipped: list[pymupdf.Rect] = []
    for rect in rects:
        if rect.y0 >= limit:
            continue
        centre = (rect.x0 + rect.x1) / 2
        if not (band_lo <= centre <= band_hi):
            continue
        box = pymupdf.Rect(rect.x0, rect.y0, rect.x1, min(rect.y1, limit))
        if box.get_area() <= 4:
            continue
        clipped.append(box)
    clipped = drop_containers(clipped)
    if not clipped:
        return None

    clipped.sort(key=lambda r: r.y1, reverse=True)
    block = [clipped[0]]
    for rect in clipped[1:]:
        if block[-1].y0 - rect.y1 > VERTICAL_GAP:
            break
        block.append(rect)
    result = block[0]
    for rect in block[1:]:
        result = result | rect

    # 图内文字标签（坐标轴、模块名、变量名）常伸出图形包围盒之外，按重叠关系并入；
    # 但并入范围限制在图形盒外扩 20 pt 以内，避免把正文行或者页面元素带进来。
    margin = pymupdf.Rect(result.x0 - 12, result.y0 - 12, result.x1 + 12, result.y1 + 12)
    for rect, text in lines:
        if rect.y0 >= limit or len(text) > 48:
            continue
        centre = (rect.x0 + rect.x1) / 2
        # 只并入完全落在"图形盒外扩 12 pt"之内的短行，杜绝正文行被误并进来。
        if band_lo <= centre <= band_hi and margin.contains(rect):
            result = result | rect
    padded = pymupdf.Rect(result.x0 - PAD, result.y0 - PAD, result.x1 + PAD, result.y1 + PAD)
    return padded & page.rect


def report(pdf: Path, pages: list[int] | None) -> list[tuple[int, pymupdf.Rect, pymupdf.Rect, str]]:
    document = pymupdf.open(pdf)
    results = []
    for index in range(document.page_count):
        page = document[index]
        if pages and (index + 1) not in pages:
            continue
        rects = graphics_rects(page)
        lines = text_lines(page)
        for caption, label in captions(page):
            box = figure_box(page, caption, rects, lines)
            if box is None:
                continue
            results.append((index + 1, box, caption, label))
    document.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", type=str, default=None, help="逗号分隔的页码，例如 2,3,5")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    mark_parser = sub.add_parser("mark")
    mark_parser.add_argument("--dpi", type=int, default=110)
    mark_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    pages = [int(item) for item in args.pages.split(",")] if args.pages else None
    rows = report(args.pdf, pages)
    for page_no, box, caption, label in rows:
        print(
            f"page {page_no}  box=[{box.x0:.1f}, {box.y0:.1f}, {box.x1:.1f}, {box.y1:.1f}]"
            f"  caption_y={caption.y0:.1f}  「{label}」"
        )

    if args.command == "mark":
        document = pymupdf.open(args.pdf)
        images = []
        for page_no, box, _, _ in rows:
            page = document[page_no - 1]
            pixmap = page.get_pixmap(dpi=args.dpi)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            scale = args.dpi / 72.0
            draw = ImageDraw.Draw(image)
            draw.rectangle(
                [box.x0 * scale, box.y0 * scale, box.x1 * scale, box.y1 * scale],
                outline=(220, 0, 0),
                width=3,
            )
            draw.text((6, 6), f"p{page_no}", fill=(220, 0, 0))
            images.append(image)
        document.close()
        if images:
            width = max(image.width for image in images)
            height = sum(image.height for image in images)
            canvas = Image.new("RGB", (width, height), "white")
            offset = 0
            for image in images:
                canvas.paste(image, (0, offset))
                offset += image.height
            canvas.save(args.out)
            print(f"{args.out}  共 {len(images)} 页，已叠加图框")


if __name__ == "__main__":
    main()
