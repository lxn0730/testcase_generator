#!/usr/bin/env python3
"""
合并所有 POINT.md 到 all_cases.md，确保相同 ITEM 只出现一次 ## 标题。

支持目录嵌套：当 ITEM 目录下还存在子目录时，子目录视为子 ITEM，
最终在 markdown 标题中以 ` / ` 拼接（如 `## 远程办公 / Offer与合同模板`）。
导入 XMind 时会自动还原为多级主题。

读取 base_dir 下任意层级的 {ITEM目录}/.../{POINT}.md，
按"叶子目录路径"分组，写出每个 ITEM 路径只有一个 ## 块的干净 all_cases.md。

用法：
    python merge_cases.py test-case-xxx/
    python merge_cases.py test-case-xxx/ -o test-case-xxx/all_cases.md -t "需求名"
"""

import sys
import re
import argparse
from pathlib import Path


SKIP_FILES = {"plan.md", "all_cases.md"}
PATH_SEP = " / "  # ITEM 路径分隔符（XMind 导入端按此切分以还原嵌套）
ORDER_PREFIX = re.compile(r"^\d+-")  # 序号前缀如 "01-"，用于强制目录排序，输出时剥离


def _clean_segment(name: str) -> str:
    """剥离目录名的 'NN-' 序号前缀（用于让物理目录按文档顺序排列，但 ITEM 路径保持干净）"""
    return ORDER_PREFIX.sub("", name)


def _strip_item_headers(lines: list[str]) -> list[str]:
    """去掉文件中 ## ITEM 级别的标题行（保留 ### 及以下）"""
    result = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^##\s", stripped) and not re.match(r"^###", stripped):
            continue
        result.append(line)
    while result and not result[0].strip():
        result.pop(0)
    return result


def merge_cases(base_dir: Path, output_path: Path, root_title: str = "测试用例") -> int:
    """
    递归遍历 base_dir，收集每个目录下的 POINT.md，按目录相对路径分组。

    Returns: 合并的 ITEM 数量
    """
    items: dict[str, list[list[str]]] = {}  # item_path -> [point_lines, ...]
    items_order: list[str] = []

    def walk(current_dir: Path, path_parts: list[str]):
        md_files = sorted(
            f for f in current_dir.glob("*.md") if f.name not in SKIP_FILES
        )
        sub_dirs = sorted(
            d for d in current_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
        )

        if md_files:
            cleaned_parts = [_clean_segment(p) for p in path_parts]
            item_name = PATH_SEP.join(cleaned_parts) if cleaned_parts else root_title
            for md_file in md_files:
                try:
                    lines = md_file.read_text(encoding="utf-8").splitlines(keepends=True)
                except Exception as e:
                    print(f"⚠️  读取失败 {md_file}: {e}", file=sys.stderr)
                    continue

                filtered = _strip_item_headers(lines)
                if not filtered:
                    continue

                if item_name not in items:
                    items[item_name] = []
                    items_order.append(item_name)
                items[item_name].append(filtered)

        for sub in sub_dirs:
            walk(sub, path_parts + [sub.name])

    top_dirs = sorted(
        d for d in base_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    )
    for top in top_dirs:
        walk(top, [top.name])

    if not items_order:
        print("⚠️  没有找到任何 POINT.md 文件", file=sys.stderr)
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {root_title}\n\n")
        for item_name in items_order:
            f.write(f"## {item_name}\n\n")
            for point_lines in items[item_name]:
                for line in point_lines:
                    f.write(line)
                if point_lines and point_lines[-1].strip():
                    f.write("\n")
                f.write("\n")

    total_points = sum(len(items[name]) for name in items_order)
    nested_cnt = sum(1 for name in items_order if PATH_SEP in name)
    extra = f"，含 {nested_cnt} 个嵌套 ITEM" if nested_cnt else ""
    print(
        f"✅ 已生成 {output_path}（{len(items_order)} 个 ITEM 路径，"
        f"{total_points} 个 POINT 文件{extra}）"
    )
    return len(items_order)


def main():
    parser = argparse.ArgumentParser(
        description="合并 POINT.md 文件到 all_cases.md（支持目录嵌套作为子 ITEM）"
    )
    parser.add_argument("dir", help="测试用例根目录（含 ITEM 子目录，可多级嵌套）")
    parser.add_argument("-o", "--output", help="输出路径（默认：<dir>/all_cases.md）")
    parser.add_argument("-t", "--title", default="测试用例", help="根节点标题")
    args = parser.parse_args()

    base_dir = Path(args.dir)
    if not base_dir.is_dir():
        print(f"❌ 目录不存在: {base_dir}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else base_dir / "all_cases.md"
    merge_cases(base_dir, output_path, args.title)


if __name__ == "__main__":
    main()
