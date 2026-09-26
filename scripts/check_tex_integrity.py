#!/usr/bin/env python3
"""核查 LaTeX 稿件的资源、引用与清点数量；语义对应由源页清单裁决。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

INPUT = re.compile(r"\\(?:input|include)\{([^{}]+)\}")
FIGURE = re.compile(r"\\begin\{(?:figure\*?|wrapfigure\*?|sidewaysfigure\*?)\}")
TABLE = re.compile(r"\\begin\{(?:table\*?|longtable|sidewaystable\*?)\}")
EQUATION = re.compile(
    r"\\begin\{(?:equation|align|gather|multline|flalign|alignat|IEEEeqnarray)\}"
)
BIBITEM = re.compile(r"\\bibitem(?:\[[^]]*\])?\{([^{}]+)\}")
BIBSOURCE = re.compile(r"\\(?:bibliography|addbibresource)\{([^{}]+)\}")
BIBENTRY = re.compile(
    r"@(?:article|book|booklet|conference|inbook|incollection|inproceedings|manual|mastersthesis|misc|phdthesis|proceedings|techreport|unpublished|online)\s*\{\s*([^,\s]+)",
    re.IGNORECASE,
)
LABEL = re.compile(r"\\label\{([^{}]+)\}")
CITE = re.compile(
    r"\\(?:[Cc]ite(?:p|t|alt|alp|author|year|yearpar|num|text)?|[Pp]arencite|"
    r"[Tt]extcite|[Aa]utocite|[Ff]ootcite|[Ss]martcite|[Ss]upercite)"
    r"\*?(?:\[[^]]*\]){0,2}\{([^{}]+)\}"
)
REF = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref)\{([^{}]+)\}")
GRAPHIC = re.compile(r"\\includegraphics(?:\[[^]]*\])?\{([^{}]+)\}")
GRAPHIC_PATH = re.compile(r"\\graphicspath\{((?:\{[^{}]*\})+)\}")
URL = re.compile(r"https?://[^\s{}\\]+")


def without_comments(source: str) -> str:
    lines = []
    for line in source.splitlines():
        for index, char in enumerate(line):
            if char != "%":
                continue
            preceding = len(line[:index]) - len(line[:index].rstrip("\\"))
            if preceding % 2 == 0:
                line = line[:index]
                break
        lines.append(line)
    return "\n".join(lines)


def collect(path: Path, seen: set[Path], errors: list[str]) -> str:
    path = path.resolve()
    if path in seen:
        return ""
    seen.add(path)
    try:
        text = without_comments(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"源稿读取失败：{path}（{exc}）")
        return ""
    parts = [text]
    for match in INPUT.finditer(text):
        name = match.group(1)
        if "\\" in name or "#" in name:
            continue
        child = path.parent / name
        if child.suffix == "":
            child = child.with_suffix(".tex")
        parts.append(collect(child, seen, errors))
    return "\n".join(parts)


def duplicates(items: list[str]) -> list[str]:
    seen: set[str] = set()
    repeats: set[str] = set()
    for item in items:
        if item in seen:
            repeats.add(item)
        seen.add(item)
    return sorted(repeats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tex", type=Path)
    parser.add_argument("--figures", type=int, help="源页清点的图形数量")
    parser.add_argument("--tables", type=int, help="源页清点的表格数量，含无编号表")
    parser.add_argument("--numbered-equations", type=int, help="源页清点的编号公式数量")
    parser.add_argument("--references", type=int, help="源页清点的参考文献条数")
    args = parser.parse_args()

    errors: list[str] = []
    text = collect(args.tex, set(), errors)
    bibitems = BIBITEM.findall(text)
    bib_texts: list[str] = []
    if not bibitems:
        for match in BIBSOURCE.finditer(text):
            for name in match.group(1).split(","):
                name = name.strip()
                path = args.tex.resolve().parent / name
                if path.suffix == "":
                    path = path.with_suffix(".bib")
                try:
                    bib_texts.append(path.read_text(encoding="utf-8"))
                except OSError as exc:
                    errors.append(f"文献数据库读取失败：{path}（{exc}）")
        bibitems = [key for body in bib_texts for key in BIBENTRY.findall(body)]

    counts = {
        "图形": (len(FIGURE.findall(text)), args.figures),
        "表格": (len(TABLE.findall(text)), args.tables),
        "编号公式": (len(EQUATION.findall(text)), args.numbered_equations),
        "参考文献": (len(bibitems), args.references),
    }
    for title, (actual, expected) in counts.items():
        print(
            f"{title}：{actual}"
            + (f" / 源页 {expected}" if expected is not None else "")
        )
        if expected is not None and actual != expected:
            errors.append(f"{title}数量与源页清点相异：{actual} / {expected}")

    labels = LABEL.findall(text)
    for title, items in (("文献键", bibitems), ("标签", labels)):
        for item in duplicates(items):
            errors.append(f"重复{title}：{item}")
    numbered = [re.fullmatch(r"([^\d]+)(\d+)", item) for item in bibitems]
    if (
        numbered
        and all(numbered)
        and len({item.group(1) for item in numbered if item}) == 1
    ):
        numbers = sorted(int(item.group(2)) for item in numbered if item)
        if numbers != list(range(1, len(numbers) + 1)):
            errors.append("数字文献键的编号序列与条目数量相异")
    known_bib = set(bibitems)
    known_labels = set(labels)
    for match in CITE.finditer(text):
        for key in match.group(1).split(","):
            key = key.strip()
            if key and key not in known_bib:
                errors.append(f"引文键缺少文献条目：{key}")
    for match in REF.finditer(text):
        if match.group(1) not in known_labels:
            errors.append(f"交叉引用缺少标签：{match.group(1)}")

    root = args.tex.resolve().parent
    prefixes = [root]
    for match in GRAPHIC_PATH.finditer(text):
        prefixes.extend(
            root / name for name in re.findall(r"\{([^{}]*)\}", match.group(1))
        )
    for match in GRAPHIC.finditer(text):
        name = match.group(1)
        if "\\" in name or "#" in name:
            continue
        candidates = []
        for prefix in prefixes:
            path = prefix / name
            candidates.extend(
                [path]
                if path.suffix
                else [
                    path.with_suffix(s)
                    for s in (".pdf", ".png", ".jpg", ".jpeg", ".eps")
                ]
            )
        if not any(item.exists() for item in candidates):
            errors.append(f"图形资源缺失：{name}")

    bibliography = (
        text.split("\\begin{thebibliography}", 1)[1]
        if "\\begin{thebibliography}" in text
        else ""
    )
    for match in URL.finditer(bibliography):
        value = match.group(0).rstrip(".,;")
        before = bibliography[max(0, match.start() - 8) : match.start()]
        if not before.endswith(("\\url{", "\\href{")):
            errors.append(f"参考文献 URL 待建立可点击链接：{value}")
        if re.search(r"https?://arxiv\.orgabs(?:/|$)|https?://arxiv\.org/abs\d", value):
            errors.append(f"参考文献 URL 路径待核对：{value}")
    for body in bib_texts:
        for match in URL.finditer(body):
            value = match.group(0).rstrip(".,;")
            if re.search(
                r"https?://arxiv\.orgabs(?:/|$)|https?://arxiv\.org/abs\d", value
            ):
                errors.append(f"参考文献 URL 路径待核对：{value}")

    unique = list(dict.fromkeys(errors))
    for issue in unique[:12]:
        print(f"待处理：{issue}")
    if len(unique) > 12:
        print(f"其余待处理项目：{len(unique) - 12} 项；处理后重新运行检查")
    print(
        "判定："
        + ("需处理上述项目" if errors else "结构检查通过；继续核对源文语义与最终页面")
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
