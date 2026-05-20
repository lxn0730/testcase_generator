#!/usr/bin/env python3
"""
测试用例 XMind 导入格式解析器

支持格式：
    #### tc-P1-功能测试: 验证xxx
    * pc: 前置条件
    * 步骤1描述
        * 预期结果1
    * 步骤2描述
        * 预期结果2.1
        * 预期结果2.2（多个预期结果会被合并）

声明规则：
    tc:              无优先级和类型
    tc-P1:           声明优先级
    tc-功能测试:      声明类型
    tc-P1-功能测试:   同时声明优先级和类型

测试类型：功能测试 | 性能测试（安全/边界/异常均归为功能测试）
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class TestCase:
    """测试用例数据结构"""
    priority: str               # P1-P5（可为空）
    title: str                  # 用例标题
    test_type: str              # 功能测试 | 性能测试
    steps: List[str] = field(default_factory=list)    # 操作步骤列表
    expected: List[str] = field(default_factory=list)  # 预期结果列表（与步骤对应，多条已合并）
    precondition: str = ""      # 前置条件
    is_negative: bool = False   # 保留兼容性字段
    note: str = ""
    line_number: int = 0
    raw_title: str = ""


class ParseError(Exception):
    def __init__(self, message: str, line_number: int = 0):
        self.message = message
        self.line_number = line_number
        super().__init__(f"Line {line_number}: {message}" if line_number else message)


class XMindFormatParser:
    """XMind 导入格式解析器"""

    VALID_TEST_TYPES = ["功能测试", "性能测试"]

    # #### tc-P1-功能测试: 标题
    CASE_PATTERN = re.compile(r'^####\s+tc([^:：]*)[：:]\s*(.+)$')

    def __init__(self, strict: bool = True):
        self.strict = strict
        self.errors: List[ParseError] = []

    def parse_file(self, file_path: Path) -> List[TestCase]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            raise ParseError(f"无法读取文件: {e}")
        return self.parse_content(content)

    def parse_content(self, content: str) -> List[TestCase]:
        lines = content.split('\n')
        cases = []
        i = 0
        while i < len(lines):
            if self.CASE_PATTERN.match(lines[i].rstrip()):
                case, next_i = self._parse_case(lines, i)
                if case:
                    cases.append(case)
                i = next_i
            else:
                i += 1
        return cases

    def _parse_modifiers(self, modifiers_str: str) -> Tuple[str, str]:
        """解析 tc 后的修饰符，例如 '-P1-功能测试' → ('P1', '功能测试')"""
        priority = ""
        test_type = ""
        if modifiers_str:
            parts = [p for p in modifiers_str.split('-') if p]
            for p in parts:
                if re.match(r'^P[1-5]$', p):
                    priority = p
                elif p:
                    test_type = p
        return priority, test_type

    def _parse_case(self, lines: List[str], start_idx: int) -> Tuple[Optional[TestCase], int]:
        title_line = lines[start_idx].rstrip()
        line_num = start_idx + 1

        m = self.CASE_PATTERN.match(title_line)
        if not m:
            return None, start_idx + 1

        priority, test_type = self._parse_modifiers(m.group(1))
        title = m.group(2).strip()

        precondition = ""
        steps: List[str] = []
        expected_groups: List[List[str]] = []  # 每个步骤对应一组预期结果

        i = start_idx + 1
        while i < len(lines):
            raw_line = lines[i]
            stripped = raw_line.strip()
            indent = len(raw_line) - len(raw_line.lstrip())

            # 遇到下一个标题节点，结束当前用例
            if stripped and re.match(r'^#{1,4}\s', stripped):
                break

            # 跳过空行
            if not stripped:
                i += 1
                continue

            # 预期结果（缩进 2+ 空格的 * 节点）
            if indent >= 2 and stripped.startswith('* '):
                content = stripped[2:].strip()
                if expected_groups:
                    expected_groups[-1].append(content)
                i += 1
                continue

            # 前置条件（pc: 声明）
            if re.match(r'^\*\s+pc[：:]\s*', stripped, re.IGNORECASE):
                pc_content = re.sub(r'^\*\s+pc[：:]\s*', '', stripped, flags=re.IGNORECASE).strip()
                precondition = pc_content
                i += 1
                continue

            # 操作步骤（无缩进的 * 节点）
            if indent == 0 and stripped.startswith('* '):
                step_content = stripped[2:].strip()
                steps.append(step_content)
                expected_groups.append([])
                i += 1
                continue

            i += 1

        # 合并每步的多条预期结果
        expected = ["；".join(grp) if grp else "" for grp in expected_groups]

        case = TestCase(
            priority=priority,
            title=title,
            test_type=test_type,
            steps=steps,
            expected=expected,
            precondition=precondition,
            line_number=line_num,
            raw_title=title_line
        )

        try:
            self._validate_case(case, line_num)
        except ParseError as e:
            if self.strict:
                raise
            self.errors.append(e)
            return None, i

        return case, i

    def _validate_case(self, case: TestCase, line_num: int):
        if not case.title:
            raise ParseError("用例标题为空", line_num)

        if not case.steps:
            raise ParseError(f"用例「{case.title}」缺少操作步骤", line_num)

        if len(case.steps) > 20:
            raise ParseError(
                f"用例「{case.title}」步骤数({len(case.steps)})超过上限20个",
                line_num
            )

        if case.priority and not re.match(r'^P[1-5]$', case.priority):
            raise ParseError(
                f"无效的优先级「{case.priority}」，必须是 P1-P5",
                line_num
            )

        if case.test_type and case.test_type not in self.VALID_TEST_TYPES:
            raise ParseError(
                f"无效的测试类型「{case.test_type}」，必须是：{', '.join(self.VALID_TEST_TYPES)}",
                line_num
            )

        if not case.title.startswith('验证'):
            raise ParseError(
                f"用例标题「{case.title}」应以「验证」开头",
                line_num
            )


# 向后兼容别名
TextProtocolParser = XMindFormatParser


def parse_test_cases(file_path: Path, strict: bool = True) -> List[TestCase]:
    parser = XMindFormatParser(strict=strict)
    return parser.parse_file(file_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python parse_text_protocol.py <文件路径>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    try:
        cases = parse_test_cases(file_path)
        print(f"✅ 解析成功，共 {len(cases)} 个用例\n")
        for idx, case in enumerate(cases, 1):
            priority_str = f"[{case.priority}]" if case.priority else "[无优先级]"
            type_str = case.test_type or "未声明"
            print(f"用例 {idx}: {priority_str} {case.title}  ({type_str})")
            if case.precondition:
                print(f"  前置条件: {case.precondition}")
            for j, step in enumerate(case.steps, 1):
                print(f"  步骤{j}: {step}")
                if j <= len(case.expected) and case.expected[j - 1]:
                    print(f"    预期: {case.expected[j - 1]}")
            print()
    except ParseError as e:
        print(f"❌ 解析失败: {e}")
        sys.exit(1)
