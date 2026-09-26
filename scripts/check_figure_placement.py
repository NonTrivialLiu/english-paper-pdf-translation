#!/usr/bin/env python3
"""比较源图与成品中实际嵌入图件的相对宽度、位置及占栏。

使用 check_figure_crop.py 的清单格式，并在顶层填写 source_text_box、
target_text_box；双栏稿可填写 target_column_width，每幅图填写 span=single/double。
正文边界可按论文或页面分别填写，单幅图的值优先于顶层值。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pymupdf


def image_placements(document: pymupdf.Document) -> dict[bytes, list[tuple[int, pymupdf.Rect]]]:
    found: dict[bytes, list[tuple[int, pymupdf.Rect]]] = defaultdict(list)
    for number, page in enumerate(document, start=1):
        for item in page.get_image_info(xrefs=True):
            xref = item["xref"]
            digest = pymupdf.Pixmap(document, xref).digest if xref else item["digest"]
            found[digest].append((number, pymupdf.Rect(item["bbox"])))
    return found


def text_box(record: dict, defaults: dict, key: str) -> tuple[float, float]:
    box = record.get(key, defaults.get(key))
    if not isinstance(box, list) or len(box) != 2 or box[1] <= box[0]:
        raise ValueError(f"图 {record.get('figure')} 缺少有效 {key}=[x0,x1]")
    return float(box[0]), float(box[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_pdf", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--assets-root", type=Path,
                        help="图件相对路径的根目录；默认使用清单所在目录")
    parser.add_argument("--width-tolerance", type=float, default=0.05,
                        help="相对正文宽度的最大比例差，默认 0.05")
    parser.add_argument("--offset-tolerance", type=float, default=0.10,
                        help="相对正文横向位置的复查阈值，默认 0.10")
    parser.add_argument("--min-effective-dpi", type=float, default=300,
                        help="排入成品后的最低有效分辨率，默认 300 dpi")
    args = parser.parse_args()

    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    defaults = data if isinstance(data, dict) else {}
    records = data.get("figures") if isinstance(data, dict) else data
    if not isinstance(records, list) or not records:
        parser.error("清单需要包含图件记录")
    root = args.assets_root or args.manifest.parent
    document = pymupdf.open(args.target_pdf)
    placements = image_placements(document)
    hard = review = 0
    for record in records:
        number = int(record["figure"])
        image_path = root / record["image"]
        errors: list[str] = []
        hints: list[str] = []
        if not image_path.is_file():
            errors.append(f"图件缺失：{image_path}")
        else:
            asset = pymupdf.Pixmap(str(image_path))
            matches = placements.get(asset.digest, [])
            if len(matches) != 1:
                hints.append(f"成品中的图件匹配数为 {len(matches)}，核对实际放置框")
            else:
                page_no, target_box = matches[0]
                source_box = pymupdf.Rect(record["box"])
                sx0, sx1 = text_box(record, defaults, "source_text_box")
                tx0, tx1 = text_box(record, defaults, "target_text_box")
                source_ratio = source_box.width / (sx1 - sx0)
                target_ratio = target_box.width / (tx1 - tx0)
                source_offset = (source_box.x0 - sx0) / (sx1 - sx0)
                target_offset = (target_box.x0 - tx0) / (tx1 - tx0)
                effective_dpi = min(
                    asset.width * 72 / target_box.width,
                    asset.height * 72 / target_box.height,
                )
                if effective_dpi < args.min_effective_dpi * 0.98:
                    errors.append(f"排入后的有效分辨率为 {effective_dpi:.0f} dpi")
                if abs(source_ratio - target_ratio) > args.width_tolerance:
                    errors.append(
                        f"相对宽度源 {source_ratio:.3f} / 成品 {target_ratio:.3f}"
                    )
                if abs(source_offset - target_offset) > args.offset_tolerance:
                    hints.append(
                        f"横向位置源 {source_offset:.3f} / 成品 {target_offset:.3f}"
                    )
                span = record.get("span")
                column_width = record.get("target_column_width",
                                          defaults.get("target_column_width"))
                if span in ("single", "double"):
                    if column_width is None:
                        errors.append("双栏占幅核查需要 target_column_width")
                    elif span == "single" and target_box.width > float(column_width) * 1.12:
                        errors.append("源图为单栏，成品图宽超过目标栏宽")
                    elif span == "double" and target_box.width <= float(column_width) * 1.12:
                        errors.append("源图为跨栏，成品图宽仍处于单栏范围")
                print(f"图 {number}：成品第 {page_no} 页，实际宽 {target_box.width:.1f} pt")
        hard += bool(errors)
        review += bool(hints)
        for item in errors:
            print(f"  差异：{item}")
        for item in hints:
            print(f"  提示：{item}")
    document.close()
    print(f"图件：{len(records)}；实质差异：{hard}；待目视复核：{review}")
    return 1 if hard else 2 if review else 0


if __name__ == "__main__":
    raise SystemExit(main())
