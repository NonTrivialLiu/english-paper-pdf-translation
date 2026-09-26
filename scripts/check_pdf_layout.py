#!/usr/bin/env python3
"""检查终稿的 A4 纸型、正文留白及主要中文书体、字号、基线间距。"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from statistics import median

import pymupdf

A4 = (595.276, 841.89)
MM_PER_PT = 25.4 / 72
SONG = r"song|fandolsong|sourcehanserif|notoserifcjk|simsun|宋|明"


def body_baselines(pages: list[dict], font: str, size: float) -> list[float]:
    gaps: list[float] = []
    for data in pages:
        lines = []
        for block in data["blocks"]:
            for line in block.get("lines", []):
                spans = [
                    span for span in line["spans"]
                    if span["font"] == font and abs(span["size"] - size) <= 0.2
                    and sum("\u3400" <= char <= "\u9fff" for char in span["text"]) >= 3
                ]
                if spans:
                    lines.append((
                        min(span["bbox"][0] for span in spans),
                        max(span["bbox"][2] for span in spans),
                        median(span["origin"][1] for span in spans),
                    ))
        for left, right, baseline in lines:
            candidates = []
            for other_left, other_right, other_baseline in lines:
                distance = other_baseline - baseline
                overlap = max(0, min(right, other_right) - max(left, other_left))
                overlap /= max(1, min(right - left, other_right - other_left))
                if 8 < distance < 20 and overlap > 0.5:
                    candidates.append(distance)
            if candidates:
                gaps.append(min(candidates))
    return gaps


def body_ink_margins(pages: list[dict], font: str, size: float,
                     page_width: float, page_height: float) -> tuple[float, float, float, float] | None:
    sampled = pages[1:-1] if len(pages) > 2 else pages
    boxes = []
    for data in sampled:
        for block in data["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if (span["font"] == font and abs(span["size"] - size) <= 0.2
                            and sum("\u3400" <= char <= "\u9fff" for char in span["text"]) >= 3):
                        boxes.append(span["bbox"])
    if len(boxes) < 20:
        return None
    return (
        min(box[0] for box in boxes) * MM_PER_PT,
        (page_width - max(box[2] for box in boxes)) * MM_PER_PT,
        min(box[1] for box in boxes) * MM_PER_PT,
        (page_height - max(box[3] for box in boxes)) * MM_PER_PT,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--body-size", type=float, default=9.0)
    parser.add_argument("--body-baseline", type=float, default=12.5)
    parser.add_argument("--margin-mm", type=float, default=16.0)
    parser.add_argument("--body-font-pattern", default=SONG)
    args = parser.parse_args()

    document = pymupdf.open(args.pdf)
    page_count = document.page_count
    page_width, page_height = document[0].rect.width, document[0].rect.height
    pages = []
    page_data = []
    text = Counter()
    for index, page in enumerate(document, start=1):
        if abs(page.rect.width - A4[0]) > 1 or abs(page.rect.height - A4[1]) > 1:
            pages.append((index, round(page.rect.width, 1), round(page.rect.height, 1)))
        data = page.get_text("dict")
        page_data.append(data)
        for block in data["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    count = sum("\u3400" <= char <= "\u9fff" for char in span["text"])
                    if count:
                        text[(span["font"], round(span["size"], 2))] += count
    document.close()

    issues = []
    hints = []
    if pages:
        issues.append(f"页面尺寸待调整：{pages[:8]}")
    if text:
        (font, size), count = text.most_common(1)[0]
        if abs(size - args.body_size) > 0.2:
            issues.append(f"中文主字号 {size} pt，目标 {args.body_size} pt")
        if re.search(args.body_font_pattern, font, re.IGNORECASE) is None:
            issues.append(f"中文正文主书体 {font} 待核对")
        print(f"中文主书体：{font}；主字号：{size} pt；字数权重：{count}")
        margins = body_ink_margins(page_data, font, size, page_width, page_height)
        if margins:
            left, right, top, bottom = margins
            print(
                f"正文文字边界留白：左 {left:.1f} / 右 {right:.1f} / "
                f"上 {top:.1f} / 下 {bottom:.1f} mm"
            )
            if abs(left - args.margin_mm) > 2.6 or abs(right - args.margin_mm) > 2.6:
                issues.append(f"左右正文留白偏离 {args.margin_mm:g} mm 页边距")
        else:
            hints.append("正文边界样本不足，页边距待逐页核对")
        gaps = body_baselines(page_data, font, size)
        if gaps:
            measured = median(gaps)
            print(f"中文正文基线间距：{measured:.2f} pt；样本：{len(gaps)} 对")
            if abs(measured - args.body_baseline) > 0.5:
                issues.append(
                    f"中文正文基线间距 {measured:.2f} pt，目标 {args.body_baseline} pt"
                )
        else:
            hints.append("中文正文基线间距待逐页核对")
    else:
        issues.append("成品未提取到中文文字层")
    print(f"纸型：{'A4' if not pages else '需调整'}；页数：{page_count}")
    for issue in issues:
        print(f"  差异：{issue}")
    for hint in hints:
        print(f"  提示：{hint}")
    return 1 if issues else 2 if hints else 0


if __name__ == "__main__":
    raise SystemExit(main())
