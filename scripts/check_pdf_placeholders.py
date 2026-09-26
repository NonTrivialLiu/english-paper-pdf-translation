#!/usr/bin/env python3
"""检查成品 PDF 的引用占位符及首页指定文字。

日志门禁只看编译日志，一旦 .aux 陈旧或只跑了一遍，`[?]`、`??` 这类标记仍会落进成品。
这里直接在 PDF 文字层里检索，作为交付前的最后一道检查。

用法：
    python check_pdf_placeholders.py 成品.pdf
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pymupdf

MARKERS = ("[?]", "??", "\\ref{", "\\cite{")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--first-page-text", action="append", default=[],
        help="应在首页文本层出现的题名、刊名等原文项目；可重复传入",
    )
    args = parser.parse_args()

    document = pymupdf.open(args.pdf)
    hits: list[tuple[int, str, str]] = []
    first_page = re.sub(r"\s+", " ", document[0].get_text()).casefold()
    for required in args.first_page_text:
        phrase = re.sub(r"\s+", " ", required).casefold()
        if phrase not in first_page:
            hits.append((1, "首页项目", required))
    for index in range(document.page_count):
        text = document[index].get_text()
        for marker in MARKERS:
            if marker in text:
                hits.append((index + 1, marker, text[:0]))
    document.close()

    print(f"成品：{args.pdf}（{args.pdf.stat().st_size} 字节）")
    if not hits:
        print("  待处理项目：0")
        print("判定：通过")
        return 0
    print(f"  待处理项目：{len(hits)}")
    for page, marker, detail in hits:
        if marker == "首页项目":
            print(f"      第 {page} 页 待核对：{detail}")
        else:
            print(f"      第 {page} 页 出现 {marker}")
    print("判定：不通过")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
