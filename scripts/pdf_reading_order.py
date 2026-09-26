#!/usr/bin/env python3
"""按栏还原双栏 PDF 的阅读顺序，输出可逐段翻译的纯文本。

双栏原刊用 `pdftotext -layout` 取文本时左右两栏逐行交错，段落被切碎，无法直接翻译。
这里按文本块中心的横坐标分栏，再按纵坐标排序，还原自然顺序。

用法：
    python pdf_reading_order.py 原文.pdf 起始页 结束页 > 正文.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf


def read_page(page: pymupdf.Page) -> dict[str, list[tuple[float, float, str]]]:
    """把一页的文本块分到左右两栏，每栏按纵向位置排序。"""

    middle = page.rect.width / 2
    columns: dict[str, list[tuple[float, float, str]]] = {"left": [], "right": []}
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        text = "\n".join(
            "".join(span["text"] for span in line["spans"]).strip()
            for line in block["lines"]
        ).strip()
        if not text:
            continue
        x0, y0, x1 = block["bbox"][0], block["bbox"][1], block["bbox"][2]
        column = "left" if (x0 + x1) / 2 < middle else "right"
        columns[column].append((y0, x0, text))
    return columns


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("first", type=int, help="起始页，从 1 开始")
    parser.add_argument("last", type=int, help="结束页，含该页")
    args = parser.parse_args()

    document = pymupdf.open(args.pdf)
    for index in range(args.first - 1, min(args.last, document.page_count)):
        print(f"\n=========== page {index + 1} ===========")
        columns = read_page(document[index])
        for name in ("left", "right"):
            for _, _, text in sorted(columns[name]):
                print(text)
    document.close()


if __name__ == "__main__":
    main()
