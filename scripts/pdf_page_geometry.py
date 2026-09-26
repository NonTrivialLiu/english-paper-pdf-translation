#!/usr/bin/env python3
"""测量原刊的页面与文本块几何，用于挑选模板的版式档位。

爱思唯尔期刊的成品页与投稿模板并不一致：elsarticle 的 3p 档正文块宽 468pt、
5p 档 522pt，页面高度默认 297mm，而实际成品常为 210×280mm。翻译稿要贴合原刊，
先量再定，不凭印象挑档。

用法：
    python pdf_page_geometry.py 原文.pdf [页码]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

MM = 25.4 / 72.0
SAME_COLUMN = 20.0   # 文本块左沿相差在该值以内，视为同一栏
MAJOR_COLUMN = 3     # 一个栏至少要容纳这么多个文本块，才算真正的栏


def describe(page: pymupdf.Page) -> None:
    blocks = [
        b for b in page.get_text("blocks")
        if b[4].strip() and (b[2] - b[0]) > 5 and (b[3] - b[1]) > 5
    ]
    if not blocks:
        print("  该页无文本块")
        return
    left = min(b[0] for b in blocks)
    right = max(b[2] for b in blocks)
    top = min(b[1] for b in blocks)
    bottom = max(b[3] for b in blocks)
    clusters: list[list[float]] = []
    for start in sorted(b[0] for b in blocks):
        if clusters and start - clusters[-1][-1] <= SAME_COLUMN:
            clusters[-1].append(start)
        else:
            clusters.append([start])
    columns = sorted((c for c in clusters if len(c) >= MAJOR_COLUMN), key=len, reverse=True)[:2]
    columns.sort()
    print(f"  页面 {page.rect.width * MM:.1f} x {page.rect.height * MM:.1f} mm "
          f"({page.rect.width:.1f} x {page.rect.height:.1f} pt)")
    print(f"  文本块 x {left:.1f}..{right:.1f}（宽 {right - left:.1f} pt）"
          f" y {top:.1f}..{bottom:.1f}")
    print("  主导栏左沿 x = " + ", ".join(f"{c[0]:.0f}" for c in columns)
          + "（表格、缩进段落会制造额外簇，栏数以目视确认为准）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("pages", nargs="*", type=int, help="页码，缺省取第 2 页与中间页")
    args = parser.parse_args()

    document = pymupdf.open(args.pdf)
    pages = args.pages or [2, document.page_count // 2]
    for number in pages:
        print(f"page {number}")
        describe(document[number - 1])
    document.close()


if __name__ == "__main__":
    main()
