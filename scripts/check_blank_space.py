#!/usr/bin/env python3
"""标出成品 PDF 中值得目视复核的纵向空白。

几何阈值提供候选页面；双栏、浮动体、首页及末页仍以渲染结果裁决。
用法：python check_blank_space.py 成品.pdf [--max-gap 40] [--strict]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pymupdf

PAGE_NUMBER = re.compile(r"^\d{1,4}$")


def content_items(page: pymupdf.Page) -> list[tuple[float, float]]:
    items: list[tuple[float, float]] = []
    for block in page.get_text("blocks"):
        text = block[4].strip()
        if not text:
            continue
        if PAGE_NUMBER.match(text) and block[1] > page.rect.height * 0.9:
            continue          # 页脚页码
        items.append((block[1], block[3]))
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width > 20 and rect.height < 60:
            items.append((rect.y0, rect.y1))
    for info in page.get_image_info():
        box = info["bbox"]
        items.append((box[1], box[3]))
    return sorted(items)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--max-gap", type=float, default=40.0)
    parser.add_argument("--min-fill", type=float, default=0.5)
    parser.add_argument("--strict", action="store_true", help="候选空白出现时返回非零")
    args = parser.parse_args()

    document = pymupdf.open(args.pdf)
    problems: list[str] = []
    report: list[tuple[int, float, float]] = []
    for index in range(document.page_count):
        page = document[index]
        items = content_items(page)
        if not items:
            continue
        gap, where = 0.0, 0.0
        prev_end = items[0][1]
        for y0, y1 in items[1:]:
            if y0 - prev_end > gap:
                gap, where = y0 - prev_end, prev_end
            prev_end = max(prev_end, y1)
        bottom = prev_end
        report.append((index + 1, gap, bottom / page.rect.height))
        last_page = index == document.page_count - 1
        if gap > args.max_gap:
            problems.append(f"第 {index + 1} 页：y={where:.0f} 起有 {gap:.0f}pt 连续空白")
        if not last_page and bottom < page.rect.height * args.min_fill:
            problems.append(f"第 {index + 1} 页：内容只排到 {bottom / page.rect.height:.0%}，其余版心空置")
    document.close()

    worst = sorted(report, key=lambda row: row[1], reverse=True)[:6]
    print(f"成品：{args.pdf}")
    print("  最大连续空白（pt）：" + "，".join(f"p{p}={g:.0f}" for p, g, _ in worst))
    if problems:
        print(f"待复核页面：{len(problems)}")
        for item in problems:
            print(f"    {item}")
        print("提示：请结合最终页面判断")
        return 1 if args.strict else 0
    print(f"待复核页面：0（阈值 {args.max_gap:.0f}pt）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
