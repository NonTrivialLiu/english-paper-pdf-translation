#!/usr/bin/env python3
"""列出图表题注、首次引用及参考文献的页码，标出需要目视复核的落位。

文本层的同名标记可能来自正文、目录或题注；输出只作为候选页面。
用法：python check_float_placement.py 排版稿.tex 成品.pdf [--max-gap 3] [--strict]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pymupdf

CAPTION_ANY = re.compile(r"\\caption\{(.*?)\}", re.S)


def captions(tex: str) -> list[tuple[str, str]]:
    r"""按文档顺序取出（类别, 题注头）；类别由 \caption 之前最近的开环境决定。"""
    out: list[tuple[str, str]] = []
    for match in CAPTION_ANY.finditer(tex):
        prefix = tex[:match.start()]
        kind = "表" if prefix.rfind("\\begin{table") > prefix.rfind("\\begin{figure") else "图"
        head = _head(match.group(1))
        if head:
            out.append((kind, head))
    return out


def _head(body: str) -> str:
    plain = re.sub(r"\\[a-zA-Z]+", "", body)
    return re.sub(r"\s+", "", plain)[:12]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tex", type=Path)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--max-gap", type=int, default=3,
                        help="提示复核的「题注页 − 首次引用页」页差，默认 3")
    parser.add_argument("--strict", action="store_true", help="出现待复核项时返回非零")
    args = parser.parse_args()

    caps = captions(args.tex.read_text(encoding="utf-8"))
    document = pymupdf.open(args.pdf)
    pages = [re.sub(r"\s+", "", document[i].get_text()) for i in range(document.page_count)]
    # 参考文献起始页要认标题块，不能认正文里出现的“参考文献”字样
    ref_page = None
    for i in range(document.page_count):
        for block in document[i].get_text("blocks"):
            head = re.sub(r"\s+", "", block[4].strip())
            if head in ("参考文献", "References") or re.match(r"^(参考文献|References)[\[\(]?1[\]\)]", head):
                ref_page = i + 1
                break
        if ref_page:
            break
    if ref_page is None:
        candidates = [i + 1 for i, text in enumerate(pages) if "[1]" in text and "[2]" in text]
        ref_page = min(candidates) if candidates else None

    problems: list[str] = []
    rows: list[tuple[str, int | None, int | None, int | None]] = []
    for kind, head in caps:
        cap_page = num = None
        for i, text in enumerate(pages):
            # 同一页里题注头可能先在别处出现（正文或别的表），逐处检查
            for match in re.finditer(re.escape(head), text):
                # 题注与编号之间的分隔符随模板而异（表1 ／ 图1: ／ 图1.），一并容许
                found = re.search(rf"{kind}(\d+)[:：.。、·\s]*$", text[max(0, match.start() - 8):match.start()])
                if found:
                    cap_page, num = i + 1, int(found.group(1))
                    break
            if cap_page:
                break
        if cap_page is None:
            rows.append((f"{kind}（题注 {head[:6]}…）", None, None, None))
            problems.append(f"{kind} 题注「{head[:10]}…」：成品里找不到")
            continue
        marker = f"{kind}{num}"
        mention_pages = [i + 1 for i, text in enumerate(pages)
                         if marker in text.replace(f"{marker}{head}", "")]
        first_ref = min(mention_pages) if mention_pages else None
        gap = None if (cap_page is None or first_ref is None) else abs(cap_page - first_ref)
        rows.append((marker, cap_page, first_ref, gap))
        if first_ref is None:
            problems.append(f"{marker}：正文里找不到引用")
        elif gap > args.max_gap:
            problems.append(f"{marker}：题注在第 {cap_page} 页，首次引用在第 {first_ref} 页，相差 {gap} 页")
        if ref_page and cap_page > ref_page:
            problems.append(f"{marker}：题注位于参考文献起始页之后（第 {cap_page} 页 > 第 {ref_page} 页）")

    print(f"成品：{args.pdf}（{document.page_count} 页；参考文献起于第 {ref_page} 页）")
    print(f"{'浮动体':<8}{'题注页':>7}{'首引页':>8}{'页差':>6}")
    for name, cap_page, first_ref, gap in rows:
        print(f"{name:<8}{str(cap_page):>7}{str(first_ref):>8}{str(gap):>6}")
    document.close()
    if problems:
        print(f"待复核图表：{len(problems)}")
        for item in problems:
            print(f"    {item}")
        print("提示：请结合原页及最终页面判断")
        return 1 if args.strict else 0
    print(f"待复核图表：0（提示页差 ≤ {args.max_gap}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
