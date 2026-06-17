#!/usr/bin/env python3
"""根据 index.json 同步 README.md 中的插件列表表格。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "index.json"
README_PATH = ROOT / "README.md"

MARKER_START = "<!-- PLUGIN_LIST_START -->"
MARKER_END = "<!-- PLUGIN_LIST_END -->"

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def render_plugin_table(plugins: list[dict]) -> str:
    if not plugins:
        return "_暂无收录插件。_\n"
    lines = [
        "| 名称 | ID | 作者 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in plugins:
        name = str(item.get("name") or item.get("id") or "").strip()
        pid = str(item.get("id") or item.get("plugin_id") or "").strip()
        author = str(item.get("author") or "").strip().lstrip("@")
        desc = str(item.get("description") or "").strip().replace("|", "\\|")
        repo = str(item.get("repository") or item.get("repository_url") or "").strip()
        homepage = str(item.get("homepage") or "").strip() or repo.removesuffix(".git")
        name_cell = f"[{name}]({homepage})" if homepage else name
        if author:
            author_cell = f"[@{author}](https://github.com/{author})"
        else:
            author_cell = "—"
        lines.append(f"| {name_cell} | `{pid}` | {author_cell} | {desc} |")
    return "\n".join(lines) + "\n"


def load_plugins(index_path: Path) -> list[dict]:
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    plugins = raw.get("plugins")
    if not isinstance(plugins, list):
        msg = f"{index_path.name} 缺少 plugins 数组"
        raise ValueError(msg)
    return plugins


def build_plugin_list_block(table: str) -> str:
    return f"{MARKER_START}\n{table.rstrip()}\n{MARKER_END}\n"


def sync_readme_content(readme_text: str, table: str) -> str:
    block = build_plugin_list_block(table)
    if MARKER_START in readme_text and MARKER_END in readme_text:
        pattern = re.compile(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n?",
            flags=re.DOTALL,
        )
        return pattern.sub(block, readme_text, count=1)

    section = (
        "## 插件列表\n\n"
        "Bot 安装时读取 `index.json`；下表由 CI 根据 JSON **自动生成**，请勿手工改表格。\n\n"
        f"{block}"
    )
    anchor = "## 站点覆盖索引"
    if anchor in readme_text:
        return readme_text.replace(anchor, f"{section}{anchor}", 1)
    return readme_text.rstrip() + "\n\n" + section


def sync_readme(
    *,
    index_path: Path = INDEX_PATH,
    readme_path: Path = README_PATH,
    write: bool = False,
) -> tuple[str, str, bool]:
    """返回 (old_readme, new_readme, changed)。"""
    plugins = load_plugins(index_path)
    table = render_plugin_table(plugins)
    old = readme_path.read_text(encoding="utf-8")
    new = sync_readme_content(old, table)
    changed = new != old
    if write and changed:
        readme_path.write_text(new, encoding="utf-8")
    return old, new, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=INDEX_PATH, help="index.json 路径")
    parser.add_argument("--readme", type=Path, default=README_PATH, help="README.md 路径")
    parser.add_argument(
        "--write",
        action="store_true",
        help="写回 README.md（默认仅 stdout 表格）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="校验 README 已与 index.json 同步；未同步则 exit 1",
    )
    args = parser.parse_args()

    if not args.index.is_file():
        print(f"缺少 {args.index}", file=sys.stderr)
        return 1
    if args.check or args.write:
        if not args.readme.is_file():
            print(f"缺少 {args.readme}", file=sys.stderr)
            return 1
        _, _, changed = sync_readme(index_path=args.index, readme_path=args.readme, write=args.write)
        if args.check and changed and not args.write:
            print(
                "README.md 插件列表与 index.json 不一致。"
                " 请运行: python tools/sync_readme.py --write",
                file=sys.stderr,
            )
            return 1
        if args.write:
            if changed:
                print(f"已更新 {args.readme.relative_to(ROOT)}")
            else:
                print("README.md 已是最新，无需变更")
        return 0

    plugins = load_plugins(args.index)
    print(render_plugin_table(plugins), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
