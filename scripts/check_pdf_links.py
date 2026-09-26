#!/usr/bin/env python3
"""检查可识别的文献与图表内部链接及目标页。

文本层分词可能影响链接分类；完整性仍须依据源稿引用清单与最终 PDF 核对。
退出码 2 表示链接分类覆盖待人工核实，退出码 1 表示目标检查有误。
用法：python check_pdf_links.py 成品.pdf
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pymupdf

# natbib 与 hyperref 会把一条引用切成若干个链接框（"[9"、"–13" 各自成框），因此分类要看
# 链接框左侧的上下文，而不是框内文本本身。
CITATION = re.compile(r"\[[\d,\s\u2013\u2014\-]+$")
FLOAT_REF = re.compile(r"(图|表)\s*(\d+)")


def page_texts(document: pymupdf.Document) -> list[str]:
    return [document[i].get_text() for i in range(document.page_count)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    document = pymupdf.open(args.pdf)
    texts = page_texts(document)
    citations: list[tuple[int, int, str]] = []
    floats: list[tuple[int, int, str, str]] = []
    others: list[tuple[int, int, str]] = []
    problems: list[str] = []
    review: list[str] = []

    for index in range(document.page_count):
        for link in document[index].get_links():
            # xdvipdfmx 常把目标写成命名目标，PyMuPDF 归类为 LINK_NAMED，一并接受。
            if link.get("kind") not in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED):
                continue
            target_page = link.get("page")
            if not isinstance(target_page, int) or not 0 <= target_page < document.page_count:
                problems.append(f"第 {index + 1} 页：内部链接目标页无法解析")
                continue
            rect = pymupdf.Rect(link["from"])
            rect_text = document[index].get_textbox(rect).strip()
            context = document[index].get_textbox(
                pymupdf.Rect(rect.x0 - 16, rect.y0 - 1, rect.x1 + 2, rect.y1 + 1)
            ).strip()
            record = (index + 1, target_page + 1, context, rect_text)
            if CITATION.search(context):
                citations.append(record)
            else:
                compact = re.sub(r"\s+", "", context)
                matches = list(FLOAT_REF.finditer(compact))
                if matches:
                    kind = matches[-1].group(1)
                    numbers = re.findall(r"\d+", rect_text)
                    number = numbers[-1] if numbers else matches[-1].group(2)
                    floats.append((index + 1, target_page + 1,
                                   context, f"{kind}{int(number)}"))
                else:
                    others.append(record)
    document.close()

    if not citations and not floats and not others:
        problems.append("成品里没有任何可识别的文献或图表跳转链接")
    elif not citations:
        review.append("内部链接存在，但文献链接识别数为零；请按源稿引文清单核查链接覆盖")

    for src, dst, text, rect_text in citations:
        # 每个链接框只覆盖一个编号或编号段，用框内编号判定目标条目。
        numbers = re.findall(r"\d+", rect_text) or re.findall(
            r"\d+", text[CITATION.search(text).start():]
        )
        marker = f"[{int(numbers[0])}]" if numbers else ""
        if not marker:
            continue
        if marker not in texts[dst - 1]:
            problems.append(f"第 {src} 页 {text} 跳到第 {dst} 页，但该页没有 {marker}")

    for src, dst, text, label in floats:
        kind, number = label[0], label[1:]
        if not re.search(rf"{kind}\s*{number}(?!\d)", texts[dst - 1]):
            problems.append(f"第 {src} 页 {text} 跳到第 {dst} 页，但该页没有 {label} 的题注")

    print(f"成品：{args.pdf}")
    print(f"  已识别文献引用链接：{len(citations)}")
    print(f"  已识别图／表引用链接：{len(floats)}")
    print(f"  其他内部链接（需对照源稿）：{len(others)}")
    if problems:
        print(f"  待处理链接问题：{len(problems)}")
        for item in problems[:12]:
            print(f"      {item}")
        print("判定：不通过")
        return 1
    if review:
        print(f"  待人工核查：{len(review)}")
        for item in review:
            print(f"      {item}")
        print("判定：需人工核实链接分类覆盖")
        return 2
    print("  已识别链接目标错误：0")
    print("提示：请对照源稿清单核验链接覆盖与目标位置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
