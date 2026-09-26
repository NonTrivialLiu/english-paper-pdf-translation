#!/usr/bin/env python3
"""汇总 LaTeX 日志。编译错误、超框、缺字与失效引用返回非零；
过松盒子及包级警告保留为逐页复核线索。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ERROR = re.compile(r"^!")
OUTPUT_WRITTEN = re.compile(r"^Output written on .+\.pdf \(\d+ pages?\)\.")
OVERFULL = re.compile(r"Overfull \\([hv])box \(([\d.]+)pt too (?:wide|high)\)")
UNDERFULL = re.compile(r"Underfull \\([hv])box")
FONT_UNDEF = re.compile(r"Font shape `([^']+)' undefined")
MISSING_CHAR = re.compile(r"Missing character:")
UNDEF_REF = re.compile(r"(Citation|Reference) `([^']+)' .*undefined")
PKG_WARN = re.compile(r"^(?:Package|LaTeX) (?:.*?)?Warning: (.*)$")


def check(log: Path) -> int:
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    errors: list[str] = []
    overfull: list[tuple[str, float, str]] = []
    underfull: list[str] = []
    fonts: list[str] = []
    missing: list[str] = []
    refs: list[str] = []
    packages: list[str] = []
    completed = False

    for line in lines:
        if OUTPUT_WRITTEN.search(line):
            completed = True
        if ERROR.match(line):
            errors.append(line[:160])
            continue
        match = OVERFULL.search(line)
        if match:
            overfull.append((match.group(1), float(match.group(2)), line[:120]))
            continue
        if UNDERFULL.search(line):
            underfull.append(line[:120])
            continue
        match = FONT_UNDEF.search(line)
        if match:
            fonts.append(match.group(1))
            continue
        if MISSING_CHAR.search(line):
            missing.append(line[:160])
            continue
        match = UNDEF_REF.search(line)
        if match:
            refs.append(f"{match.group(1)} {match.group(2)}")
            continue
        match = PKG_WARN.match(line)
        if match and "rerun" not in match.group(1):
            packages.append(match.group(1)[:120])

    if not completed:
        errors.append("日志缺少 PDF 写入完成标记")

    print(f"日志：{log}")
    print(f"  错误          : {len(errors)}")
    for item in errors[:6]:
        print(f"      {item}")
    print(f"  盒子溢出      : {len(overfull)}" + (
        "".join(f"\n      {box}box {amount:.1f}pt  {text}" for box, amount, text in overfull)
        if overfull else ""
    ))
    print(f"  盒子过松      : {len(underfull)}")
    print(f"  字形缺位      : {len(set(fonts))}")
    print(f"  缺字（无字形）: {len(set(missing))}" + (
        "".join(f"\n      {item}" for item in sorted(set(missing))) if missing else ""
    ))
    print(f"  引用未定义    : {len(refs)}")
    print(f"  包级警告      : {len(packages)}")
    for text in packages[:6]:
        print(f"      {text}")

    hard = bool(errors or overfull or fonts or missing or refs)
    verdict = "不通过（存在硬性缺陷）" if hard else (
        "通过；请复核过松盒子与包级警告" if underfull or packages else "通过"
    )
    print("判定：" + verdict)
    return 1 if hard else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", type=Path, nargs="+")
    args = parser.parse_args()
    status = 0
    for log in args.logs:
        status |= check(log)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
