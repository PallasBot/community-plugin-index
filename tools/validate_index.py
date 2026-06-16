#!/usr/bin/env python3
"""校验 index.json 结构与 plugin id 唯一性。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "index.json"
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALLOWED_REPO_PREFIX = ("https://", "git@")


def fail(msg: str) -> None:
    print(f"validate_index: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if not INDEX_PATH.is_file():
        fail(f"缺少 {INDEX_PATH.name}")
    try:
        raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"JSON 无效：{e}")

    if not isinstance(raw, dict):
        fail("根对象须为 JSON 对象")
    if raw.get("version") != 1:
        fail("version 须为整数 1")
    plugins = raw.get("plugins")
    if not isinstance(plugins, list):
        fail("plugins 须为数组")

    seen: set[str] = set()
    for i, item in enumerate(plugins):
        if not isinstance(item, dict):
            fail(f"plugins[{i}] 须为对象")
        pid = str(item.get("id") or "").strip()
        if not PLUGIN_ID_RE.fullmatch(pid):
            fail(f"plugins[{i}].id 非法：{pid!r}")
        if pid in seen:
            fail(f"重复 plugin id：{pid}")
        seen.add(pid)
        repo = str(item.get("repository") or "").strip()
        if not repo.startswith(ALLOWED_REPO_PREFIX):
            fail(f"plugins[{i}].repository 须为 https:// 或 git@ 开头")
        ref = item.get("ref")
        if ref is not None and not str(ref).strip():
            fail(f"plugins[{i}].ref 不能为空字符串")

    print(f"OK: {len(plugins)} plugin(s)")


if __name__ == "__main__":
    main()
