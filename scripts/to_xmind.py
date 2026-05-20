#!/usr/bin/env python3
"""
测试用例导出 XMind 工具

从 all_cases.md 或目录生成 XMind 文件(.xmind)

格式基于对真实 XMind 文件逆向分析，包含：
  - content.json   （主内容，JSON 格式）
  - metadata.json  （含 dataStructureVersion / layoutEngineVersion）
  - manifest.json  （声明文件入口，XMind 用来校验合法性）
  - Thumbnails/thumbnail.png

用法：
    python to_xmind.py all_cases.md -o output.xmind [-t "根节点标题"]
    python to_xmind.py test-case-xxx/  -o output.xmind [-t "根节点标题"]
"""

import sys
import re
import json
import uuid
import struct
import zlib
import zipfile
import argparse
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from parse_text_protocol import XMindFormatParser, TestCase


# ITEM 路径分隔符（与 merge_cases.py 保持一致）
ITEM_PATH_SEP = " / "


def _split_item_path(item: str) -> List[str]:
    """将 `## A / B / C` 形式的 ITEM 名拆分为 [A, B, C]，用于还原嵌套主题"""
    if not item:
        return []
    parts = [p.strip() for p in item.split("/")]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def gen_id() -> str:
    return "node_" + uuid.uuid4().hex[:20]


def _minimal_png() -> bytes:
    """生成最小的 1×1 白色 RGB PNG"""
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(ctype: bytes, data: bytes) -> bytes:
        payload = ctype + data
        crc = struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + payload + crc

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


# ---------------------------------------------------------------------------
# Parsing helpers（与之前保持一致）
# ---------------------------------------------------------------------------

def parse_all_cases_md(file_path: Path) -> List[Dict]:
    result: List[Dict] = []
    current_item = ""
    current_point = ""

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if re.match(r"^##\s", stripped) and not re.match(r"^###", stripped):
            current_item = stripped[2:].strip()
            i += 1
            continue

        if re.match(r"^###\s", stripped) and not re.match(r"^####", stripped):
            current_point = stripped[3:].strip()
            i += 1
            continue

        if re.match(r"^####\s+tc", stripped):
            case_lines = [line]
            i += 1
            while i < len(lines):
                next_stripped = lines[i].strip()
                if re.match(r"^#{1,4}\s", next_stripped):
                    break
                case_lines.append(lines[i].rstrip())
                i += 1
            parser = XMindFormatParser(strict=False)
            for case in parser.parse_content("\n".join(case_lines)):
                _append_case(result, current_item, current_point, case)
            continue

        i += 1

    return result


def _append_case(result: List[Dict], item: str, point: str, case: TestCase):
    for entry in result:
        if entry["item"] == item and entry["point"] == point:
            entry["cases"].append(case)
            return
    result.append({"item": item, "point": point, "cases": [case]})


def parse_directory(dir_path: Path) -> List[Dict]:
    """递归遍历目录；目录嵌套层级会被拼成 ITEM 路径（` / ` 分隔）"""
    all_cases_file = dir_path / "all_cases.md"
    if all_cases_file.exists():
        return parse_all_cases_md(all_cases_file)

    result: List[Dict] = []

    def walk(current: Path, path_parts: List[str]):
        md_files = sorted(
            f for f in current.glob("*.md")
            if f.name not in ("plan.md", "all_cases.md")
        )
        if md_files and path_parts:
            item_name = ITEM_PATH_SEP.join(path_parts)
            for md_file in md_files:
                parser = XMindFormatParser(strict=False)
                try:
                    cases = parser.parse_file(md_file)
                    if cases:
                        result.append({
                            "item": item_name,
                            "point": md_file.stem,
                            "cases": cases,
                        })
                except Exception as e:
                    print(f"⚠️  解析失败 {md_file}: {e}")

        for sub in sorted(d for d in current.iterdir() if d.is_dir() and not d.name.startswith(".")):
            walk(sub, path_parts + [sub.name])

    for top in sorted(d for d in dir_path.iterdir() if d.is_dir() and not d.name.startswith(".")):
        walk(top, [top.name])
    return result


# ---------------------------------------------------------------------------
# XMind JSON content builder
# ---------------------------------------------------------------------------

def _case_topic(case: TestCase) -> Dict:
    """测试用例 → topic dict（含前置条件和步骤子节点）"""
    parts = []
    if case.priority:
        parts.append(case.priority)
    if getattr(case, "test_type", None):
        parts.append(case.test_type)
    prefix = f"tc-{'-'.join(parts)}: " if parts else ""
    title = f"{prefix}{case.title}"

    children = []
    if case.precondition:
        children.append({"id": gen_id(), "title": f"前置条件: {case.precondition}"})

    for i, step in enumerate(case.steps):
        step_node: Dict = {"id": gen_id(), "title": step}
        if i < len(case.expected) and case.expected[i]:
            step_node["children"] = {
                "attached": [{"id": gen_id(), "title": case.expected[i]}]
            }
        children.append(step_node)

    topic: Dict = {"id": gen_id(), "title": title}
    if children:
        topic["children"] = {"attached": children}
    return topic


def build_content_json(entries: List[Dict], root_title: str) -> List[Dict]:
    # 构建目录树：每个节点保存 子 ITEM 节点 和 直属 POINT
    class _Node:
        __slots__ = ("name", "subs", "subs_order", "points", "points_order")

        def __init__(self, name: str):
            self.name = name
            self.subs: Dict[str, "_Node"] = {}
            self.subs_order: List[str] = []
            self.points: Dict[str, List[TestCase]] = {}
            self.points_order: List[str] = []

        def child(self, name: str) -> "_Node":
            if name not in self.subs:
                self.subs[name] = _Node(name)
                self.subs_order.append(name)
            return self.subs[name]

    root_node = _Node(root_title)

    for entry in entries:
        path_parts = _split_item_path(entry["item"])
        node = root_node
        for part in path_parts:
            node = node.child(part)
        point = entry["point"]
        if point not in node.points:
            node.points[point] = []
            node.points_order.append(point)
        node.points[point].extend(entry["cases"])

    def _build_topic(node: _Node) -> Dict:
        children = []
        for sub_name in node.subs_order:
            children.append(_build_topic(node.subs[sub_name]))
        for point_name in node.points_order:
            case_topics = [_case_topic(c) for c in node.points[point_name]]
            point_node: Dict = {"id": gen_id(), "title": point_name}
            if case_topics:
                point_node["children"] = {"attached": case_topics}
            children.append(point_node)
        topic: Dict = {"id": gen_id(), "title": node.name}
        if children:
            topic["children"] = {"attached": children}
        return topic

    item_topics: List[Dict] = []
    for sub_name in root_node.subs_order:
        item_topics.append(_build_topic(root_node.subs[sub_name]))
    for point_name in root_node.points_order:
        case_topics = [_case_topic(c) for c in root_node.points[point_name]]
        point_node = {"id": gen_id(), "title": point_name}
        if case_topics:
            point_node["children"] = {"attached": case_topics}
        item_topics.append(point_node)

    root_topic: Dict = {
        "id": gen_id(),
        "class": "topic",
        "title": root_title,
        "structureClass": "org.xmind.ui.logic.right",
    }
    if item_topics:
        root_topic["children"] = {"attached": item_topics}

    sheet: Dict = {
        "id": gen_id(),
        "class": "sheet",
        "title": root_title,
        "rootTopic": root_topic,
    }
    return [sheet]


# ---------------------------------------------------------------------------
# XMind file writer
# ---------------------------------------------------------------------------

def generate_xmind(entries: List[Dict], output_path: Path, root_title: str = "测试用例"):
    content = build_content_json(entries, root_title)

    metadata = {
        "dataStructureVersion": "2",
        "creator": {"name": "testcase-generator", "version": "1.0"},
        "layoutEngineVersion": "3",
    }

    manifest = {
        "file-entries": {
            "content.json": {},
            "metadata.json": {},
            "Thumbnails/thumbnail.png": {},
        }
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.json",   json.dumps(content,  ensure_ascii=False))
        zf.writestr("metadata.json",  json.dumps(metadata, ensure_ascii=False))
        zf.writestr("manifest.json",  json.dumps(manifest, ensure_ascii=False))
        zf.writestr("Thumbnails/thumbnail.png", _minimal_png())

    total = sum(len(e["cases"]) for e in entries)
    print(f"✅ XMind 导出成功: {output_path}（{total} 个用例）")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="将测试用例导出为 XMind 格式")
    parser.add_argument("input", help="输入文件（all_cases.md）或目录路径")
    parser.add_argument("-o", "--output", required=True, help="输出 .xmind 文件路径")
    parser.add_argument("-t", "--title", default="测试用例", help="根节点标题（默认：测试用例）")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"❌ 路径不存在: {input_path}")
        sys.exit(1)

    print(f"开始导出 XMind: {input_path}\n")

    if input_path.is_file():
        entries = parse_all_cases_md(input_path)
    elif input_path.is_dir():
        entries = parse_directory(input_path)
    else:
        print(f"❌ 无效路径: {input_path}")
        sys.exit(1)

    if not entries:
        print("⚠️  没有找到任何测试用例")
        sys.exit(0)

    generate_xmind(entries, output_path, args.title)


if __name__ == "__main__":
    main()
