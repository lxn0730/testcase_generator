#!/usr/bin/env python3
"""
校验 plan.md 复杂度分、结构标签、推理外显字段的一致性。

规则：
- 复杂度分 ≤ 8 → 必须 "结构: 扁平"，且其下不应出现 "子ITEM:" 行
- 复杂度分 ≥ 9 → 必须 "结构: 嵌套"，且其下必须有至少 1 行 "子ITEM:"
- 每个功能必须有 "结构判定:" 行，分数和结构标签需与头部一致
- 每个功能必须有 "评分构成:" 行，末尾 "= N" 需等于复杂度分；各加分项之和也需等于该 N

用法：
    python3 validate_plan.py path/to/plan.md
退出码：0 通过；1 存在违规。
"""
import re
import sys
from pathlib import Path

HEADER = re.compile(r"^###\s+(?P<name>.+?)\s*\[复杂度分[:：]\s*(?P<score>\d+)[，,]\s*结构[:：]\s*(?P<structure>扁平|嵌套)\s*\]\s*$")
SUBITEM = re.compile(r"^\s*子ITEM[:：]")
DECISION = re.compile(r"^\s*结构判定[:：]\s*(?P<score>\d+)\s*(?P<op>≥|>=|≤|<=)\s*(?P<thr>\d+)\s*(?:→|->)\s*(?P<structure>扁平|嵌套)")
BREAKDOWN = re.compile(r"^\s*评分构成[:：]\s*(?P<body>.+?)\s*=\s*(?P<total>\d+)\s*$")
ADDEND = re.compile(r"\+\s*(\d+)")


def validate(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    errors: list[str] = []

    blocks: list[tuple[int, str, int, str]] = []
    for i, line in enumerate(lines):
        m = HEADER.match(line)
        if m:
            blocks.append((i, m.group("name"), int(m.group("score")), m.group("structure")))

    for idx, (lineno, name, score, structure) in enumerate(blocks):
        end = blocks[idx + 1][0] if idx + 1 < len(blocks) else len(lines)
        body = lines[lineno + 1:end]
        has_subitem = any(SUBITEM.match(l) for l in body)

        if score >= 9 and structure == "扁平":
            errors.append(f"L{lineno+1} [{name}] 复杂度分 {score} ≥ 9 但标记为扁平 — 必须改为嵌套")
        if score <= 8 and structure == "嵌套":
            errors.append(f"L{lineno+1} [{name}] 复杂度分 {score} ≤ 8 但标记为嵌套 — 建议改为扁平")
        if structure == "嵌套" and not has_subitem:
            errors.append(f"L{lineno+1} [{name}] 标记为嵌套但缺少 '子ITEM:' 行")
        if structure == "扁平" and has_subitem:
            errors.append(f"L{lineno+1} [{name}] 标记为扁平但出现 '子ITEM:' 行")

        decision_line = None
        breakdown_line = None
        for offset, line in enumerate(body):
            if decision_line is None and DECISION.match(line):
                decision_line = (lineno + 1 + offset, DECISION.match(line))
            if breakdown_line is None and BREAKDOWN.match(line):
                breakdown_line = (lineno + 1 + offset, BREAKDOWN.match(line))

        if decision_line is None:
            errors.append(f"L{lineno+1} [{name}] 缺少 '结构判定:' 行（格式: 结构判定: N ≥9/≤8 → 嵌套/扁平）")
        else:
            dl, dm = decision_line
            d_score = int(dm.group("score"))
            d_structure = dm.group("structure")
            if d_score != score:
                errors.append(f"L{dl+1} [{name}] 结构判定行的分数 {d_score} 与头部 {score} 不一致")
            if d_structure != structure:
                errors.append(f"L{dl+1} [{name}] 结构判定行的结构 '{d_structure}' 与头部 '{structure}' 不一致")

        if breakdown_line is None:
            errors.append(f"L{lineno+1} [{name}] 缺少 '评分构成:' 行（格式: 评分构成: 项A+N | 项B+M | ... = 总分）")
        else:
            bl, bm = breakdown_line
            total = int(bm.group("total"))
            addends = [int(x) for x in ADDEND.findall(bm.group("body"))]
            if total != score:
                errors.append(f"L{bl+1} [{name}] 评分构成末尾 = {total} 与头部复杂度分 {score} 不一致")
            if addends and sum(addends) != total:
                errors.append(f"L{bl+1} [{name}] 评分构成加分项之和 {sum(addends)} ≠ 末尾 = {total}")
            if not addends:
                errors.append(f"L{bl+1} [{name}] 评分构成行未识别到任何 '+N' 加分项")

    return errors


def main():
    if len(sys.argv) != 2:
        print("用法: validate_plan.py <plan.md>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(2)
    errors = validate(path)
    if errors:
        print(f"❌ plan.md 校验失败 ({len(errors)} 项):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("✅ plan.md 复杂度/结构一致性校验通过")


if __name__ == "__main__":
    main()
