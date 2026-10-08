"""为已收录社区插件创建版本更新 PR；默认只预览，不写 GitHub。"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import re
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

CENTRAL = "PallasBot/community-plugin-index"
PILOT = {"memes": "TogetsuDo/pallas-plugin-memes"}
SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
ROOT = Path(__file__).resolve().parents[1]


class GitHub:
    def request(self, method: str, path: str, data: object | None = None) -> object:
        command = ["gh", "api", "--method", method]
        if data is not None:
            command += ["--input", "-"]
        command.append(path)
        # 固定 gh argv；受控端点不会变成选项，JSON 仅通过 stdin 传入。
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        result = subprocess.run(
            command,
            input=None if data is None else json.dumps(data),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None


def semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ValueError(f"版本必须是正式 ASCII semver X.Y.Z：{value!r}")
    return tuple(map(int, value.split(".")))  # type: ignore[return-value]


def decode_content(value: object) -> str:
    if not isinstance(value, dict) or value.get("encoding") != "base64":
        raise ValueError("GitHub contents 响应不是 base64 文件")
    return base64.b64decode(value["content"], validate=False).decode("utf-8")


def github_repo(repository: object) -> str:
    if not isinstance(repository, str):
        raise TypeError("repository 无效")
    parsed = urlsplit(repository)
    match = re.fullmatch(
        r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?", parsed.path
    )
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not match
    ):
        raise ValueError(
            f"repository 必须是 https://github.com/owner/repo：{repository!r}"
        )
    return f"{match.group(1)}/{match.group(2)}"


def get_json_file(api: GitHub, repo: str, path: str, ref: str) -> object:
    return json.loads(
        decode_content(api.request("GET", f"repos/{repo}/contents/{path}?ref={ref}"))
    )


def resolve_tag_commit(api: GitHub, repo: str, version: str, tag: str) -> str:
    if tag != f"v{version}":
        raise ValueError("tag 必须精确等于 v{version}")
    ref = api.request("GET", f"repos/{repo}/git/ref/tags/{tag}")
    if not isinstance(ref, dict) or ref.get("ref") != f"refs/tags/{tag}":
        raise ValueError("Git tag ref 不匹配")
    obj = ref.get("object")
    seen: set[str] = set()
    for _ in range(5):
        if (
            not isinstance(obj, dict)
            or not SHA.fullmatch(str(obj.get("sha", "")))
            or obj["sha"] in seen
        ):
            raise ValueError("Git tag 对象无效或循环")
        sha = obj["sha"]
        seen.add(sha)
        kind = obj.get("type")
        if kind == "commit":
            commit = api.request("GET", f"repos/{repo}/git/commits/{sha}")
            if not isinstance(commit, dict) or commit.get("sha") != sha:
                raise ValueError("tag 最终对象不是有效 commit")
            return sha
        if kind != "tag":
            raise ValueError(f"不支持的 tag 对象类型：{kind!r}")
        annotated = api.request("GET", f"repos/{repo}/git/tags/{sha}")
        obj = annotated.get("object") if isinstance(annotated, dict) else None
    raise ValueError("annotated tag peel 超过 5 层")


def metadata_version(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError("__init__.py 语法无效") from exc
    declarations = [node for node in ast.walk(tree) if binds_metadata(node)]
    if len(declarations) != 1 or not isinstance(declarations[0], ast.Assign):
        raise ValueError("__plugin_meta__ 必须是唯一的顶层简单赋值")
    assignment = declarations[0]
    if (
        assignment not in tree.body
        or len(assignment.targets) != 1
        or not isinstance(assignment.targets[0], ast.Name)
    ):
        raise ValueError("__plugin_meta__ 必须是唯一的顶层简单赋值")
    call = assignment.value
    if (
        not isinstance(call, ast.Call)
        or not isinstance(call.func, ast.Name)
        or call.func.id != "PluginMetadata"
    ):
        raise ValueError("__plugin_meta__ 必须直接调用 PluginMetadata")
    extra_keywords = [keyword for keyword in call.keywords if keyword.arg == "extra"]
    if len(extra_keywords) != 1 or any(
        keyword.arg is None for keyword in call.keywords
    ):
        raise ValueError("PluginMetadata.extra 必须是唯一且显式的字典参数")
    extra = extra_keywords[0].value
    if not isinstance(extra, ast.Dict):
        raise TypeError("PluginMetadata.extra 必须是字面量字典")
    versions = []
    for key, value in zip(extra.keys, extra.values):
        if (
            key is None
            or not isinstance(key, ast.Constant)
            or not isinstance(key.value, str)
        ):
            raise ValueError("PluginMetadata.extra 不支持展开或非字面量键")
        if key.value == "version":
            versions.append(value)
    if (
        len(versions) != 1
        or not isinstance(versions[0], ast.Constant)
        or not isinstance(versions[0].value, str)
    ):
        raise ValueError("PluginMetadata.extra.version 必须是唯一的字面量字符串")
    return versions[0].value


def targets_name(target: ast.expr) -> bool:
    if isinstance(target, ast.Name):
        return target.id == "__plugin_meta__"
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(targets_name(item) for item in target.elts)
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        return targets_name(target.value)
    return False


def binds_metadata(node: ast.AST) -> bool:
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
        targets = (
            node.targets
            if isinstance(node, (ast.Assign, ast.Delete))
            else [node.target]
        )
        return any(targets_name(target) for target in targets)
    if isinstance(node, (ast.NamedExpr, ast.For, ast.AsyncFor)):
        return targets_name(node.target)
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return any(
            item.optional_vars and targets_name(item.optional_vars)
            for item in node.items
        )
    if isinstance(node, ast.ExceptHandler):
        return node.name == "__plugin_meta__"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == "__plugin_meta__"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return any(
            (alias.asname or alias.name.split(".")[0]) == "__plugin_meta__"
            for alias in node.names
        )
    if isinstance(node, (ast.MatchAs, ast.MatchStar)):
        return node.name == "__plugin_meta__"
    if isinstance(node, ast.MatchMapping):
        return node.rest == "__plugin_meta__"
    return isinstance(node, ast.TypeAlias) and targets_name(node.name)


def validate_date(value: object, today: date) -> date:
    if not isinstance(value, str):
        raise TypeError("候选 updated_at 必须是 ISO 日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("候选 updated_at 必须是 ISO 日期") from exc
    if parsed.isoformat() != value or parsed > today:
        raise ValueError("候选 updated_at 必须是有效且不晚于今天的 ISO 日期")
    return parsed


def validate_release(api: GitHub, repo: str, commit: str, version: str) -> None:
    entry = get_json_file(api, repo, "community-index.entry.json", commit)
    if (
        not isinstance(entry, dict)
        or entry.get("id") != "memes"
        or github_repo(entry.get("repository")) != repo
        or entry.get("ref") != "main"
    ):
        raise ValueError("插件收录元数据与可信索引不匹配")
    changelog = decode_content(
        api.request("GET", f"repos/{repo}/contents/CHANGELOG.md?ref={commit}")
    )
    headings = re.findall(r"^## \[([^\]]+)\](?: - .*?)?$", changelog, re.MULTILINE)
    changelog_version = next(
        (heading for heading in headings if heading.casefold() != "unreleased"), None
    )
    versions = (
        entry.get("version"),
        metadata_version(
            decode_content(
                api.request("GET", f"repos/{repo}/contents/__init__.py?ref={commit}")
            )
        ),
        changelog_version,
    )
    if any(item != version for item in versions):
        raise ValueError(
            f"tag、插件元数据、CHANGELOG 版本不一致：{versions!r}，期望 {version}"
        )


def build_candidate(
    index: object, plugin_id: str, version: str, today: str
) -> dict | None:
    new_version = semver(version)
    if plugin_id not in PILOT:
        raise ValueError(f"暂不支持插件：{plugin_id}")
    if not isinstance(index, dict) or not isinstance(index.get("plugins"), list):
        raise TypeError("可信 index 格式无效")
    matches = [
        item
        for item in index["plugins"]
        if isinstance(item, dict) and item.get("id") == plugin_id
    ]
    if len(matches) != 1:
        raise ValueError(f"索引中必须且只能有一个 {plugin_id}")
    plugin = matches[0]
    repo = github_repo(plugin.get("repository"))
    if repo.casefold() != PILOT[plugin_id].casefold():
        raise ValueError(f"{plugin_id} repository 不符合试点仓库映射")
    old_version = semver(plugin.get("version"))
    if new_version == old_version:
        return None
    if new_version < old_version:
        raise ValueError("拒绝版本降级")
    candidate = deepcopy(index)
    next(item for item in candidate["plugins"] if item["id"] == plugin_id)[
        "version"
    ] = version
    candidate["updated_at"] = today
    return candidate


def validate_local(candidate: dict, snapshot_sha: str) -> None:
    # 使用现有仓库门禁，临时副本不改工作树文件。
    import tempfile

    if not SHA.fullmatch(snapshot_sha):
        raise ValueError("本地验证缺少固定 main SHA")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "tools").mkdir()
        path = root / "index.json"
        path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (root / "tools/validate_index.py").write_text(
            (ROOT / "tools/validate_index.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        # 仅执行已核验 main 字节的固定 validator，候选 JSON 不作为代码执行。
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        subprocess.run(
            [sys.executable, str(root / "tools/validate_index.py")],
            cwd=temp,
            check=True,
            capture_output=True,
            text=True,
        )
        # 固定 argv 与 --check；脚本字节已核验，JSON/README 不进入执行通路。
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/sync_readme.py"),
                "--index",
                str(path),
                "--readme",
                str(ROOT / "README.md"),
                "--check",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


def verify_snapshot(api: GitHub) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    checkout_sha = result.stdout.strip()
    if not SHA.fullmatch(checkout_sha):
        raise ValueError("本地 checkout HEAD 无效")
    main_ref = api.request("GET", f"repos/{CENTRAL}/git/ref/heads/main")
    main_sha = (
        main_ref.get("object", {}).get("sha") if isinstance(main_ref, dict) else None
    )
    if main_sha != checkout_sha:
        raise ValueError("本地 checkout 与中央 main 不一致，请更新工作区后重试")
    for relative in ("tools/validate_index.py", "tools/sync_readme.py", "README.md"):
        committed = subprocess.run(
            ["git", "show", f"{checkout_sha}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        if (ROOT / relative).read_bytes() != committed:
            raise ValueError(f"本地发布门禁文件存在未提交修改：{relative}")
    return checkout_sha


def require_main(api: GitHub, expected_main_sha: str) -> None:
    ref = api.request("GET", f"repos/{CENTRAL}/git/ref/heads/main")
    current = ref.get("object", {}).get("sha") if isinstance(ref, dict) else None
    if current != expected_main_sha:
        raise ValueError("中央 main 已变化，停止写入并请重新运行")


def paged(api: GitHub, path: str) -> list[dict]:
    result = []
    page = 1
    while True:
        batch = api.request("GET", f"{path}&per_page=100&page={page}")
        if not isinstance(batch, list):
            raise TypeError("GitHub PR 列表响应无效")
        result.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            return result
        page += 1


def pull_belongs_to_central_main(pull: dict) -> bool:
    head = pull.get("head")
    base = pull.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        return False
    head_repo = head.get("repo") or {}
    base_repo = base.get("repo") or {}
    return (
        isinstance(head_repo, dict)
        and isinstance(base_repo, dict)
        and str(head_repo.get("full_name", "")).casefold() == CENTRAL.casefold()
        and str(base_repo.get("full_name", "")).casefold() == CENTRAL.casefold()
        and base.get("ref") == "main"
    )


def tree_files(api: GitHub, repo: str, sha: str) -> dict[str, tuple[str, str, str]]:
    commit = api.request("GET", f"repos/{repo}/git/commits/{sha}")
    tree_sha = commit.get("tree", {}).get("sha") if isinstance(commit, dict) else None
    tree = (
        api.request("GET", f"repos/{repo}/git/trees/{tree_sha}?recursive=1")
        if tree_sha
        else None
    )
    if not isinstance(tree, dict) or tree.get("truncated"):
        raise ValueError("无法安全校验索引分支文件树")
    files = {}
    for item in tree.get("tree", []):
        if not isinstance(item, dict) or item.get("type") == "tree":
            continue
        if not all(
            isinstance(item.get(key), str) for key in ("path", "mode", "type", "sha")
        ):
            raise ValueError("GitHub tree 包含无效叶节点")
        files[item["path"]] = (item["mode"], item["type"], item["sha"])
    return files


def find_target_pull(api: GitHub, plugin_id: str, branch: str) -> dict | None:
    pulls = paged(api, f"repos/{CENTRAL}/pulls?state=all")
    target = []
    for pull in pulls:
        if not pull_belongs_to_central_main(pull):
            continue
        head = pull.get("head", {}).get("ref", "")
        if not isinstance(head, str):
            continue
        if head == branch:
            target.append(pull)
        elif head.startswith(f"chore/{plugin_id}-v") and pull.get("state") == "open":
            raise ValueError(f"存在同插件其他版本开放 PR：{pull.get('html_url')}")
    if any(
        pull.get("state") == "closed" and not pull.get("merged_at") for pull in target
    ):
        raise ValueError("目标版本已有未合并关闭 PR，拒绝重复创建")
    return next((pull for pull in target if pull.get("state") == "open"), None)


def existing_branch(
    api: GitHub,
    branch: str,
    expected_main_sha: str,
    expected_index_sha: str,
    candidate: dict,
    today: date,
) -> tuple[str, str | None, str]:
    main_ref = api.request("GET", f"repos/{CENTRAL}/git/ref/heads/main")
    base = main_ref.get("object", {}).get("sha") if isinstance(main_ref, dict) else None
    if (
        base != expected_main_sha
        or not isinstance(base, str)
        or not SHA.fullmatch(base)
    ):
        raise ValueError("中央 main 已变化或 ref 无效")
    base_commit = api.request("GET", f"repos/{CENTRAL}/git/commits/{base}")
    base_tree_sha = (
        base_commit.get("tree", {}).get("sha")
        if isinstance(base_commit, dict)
        else None
    )
    base_tree = (
        api.request("GET", f"repos/{CENTRAL}/git/trees/{base_tree_sha}?recursive=1")
        if base_tree_sha
        else None
    )
    if (
        not isinstance(base_tree, dict)
        or base_tree.get("truncated")
        or not isinstance(base_tree_sha, str)
    ):
        raise ValueError("无法校验当前 main 文件树")
    base_index = next(
        (
            item
            for item in base_tree.get("tree", [])
            if isinstance(item, dict) and item.get("path") == "index.json"
        ),
        None,
    )
    if (
        not base_index
        or base_index.get("mode") != "100644"
        or base_index.get("type") != "blob"
        or base_index.get("sha") != expected_index_sha
    ):
        raise ValueError("main 的 index.json 已在候选生成后变化，请重新运行")
    try:
        ref = api.request("GET", f"repos/{CENTRAL}/git/ref/heads/{branch}")
    except subprocess.CalledProcessError as exc:
        if "HTTP 404" not in (exc.stderr or ""):
            raise
        return base, None, base_tree_sha
    head_sha = ref.get("object", {}).get("sha") if isinstance(ref, dict) else None
    branch_commit = api.request("GET", f"repos/{CENTRAL}/git/commits/{head_sha}")
    if (
        not isinstance(branch_commit, dict)
        or len(branch_commit.get("parents", [])) != 1
        or branch_commit["parents"][0].get("sha") != base
    ):
        raise ValueError("既有分支不是当前 main 的直接子提交，需人工处理冲突")
    base_files, head_files = (
        tree_files(api, CENTRAL, base),
        tree_files(api, CENTRAL, head_sha),
    )
    changed = {
        path
        for path in base_files.keys() | head_files.keys()
        if base_files.get(path) != head_files.get(path)
    }
    if changed != {"index.json"}:
        raise ValueError(f"既有分支包含非预期文件变更：{sorted(changed)}")
    if any(
        files.get("index.json", ())[:2] != ("100644", "blob")
        for files in (base_files, head_files)
    ):
        raise ValueError("main 与目标分支的 index.json 必须是普通文件")
    blob = api.request("GET", f"repos/{CENTRAL}/contents/index.json?ref={head_sha}")
    branch_index = json.loads(decode_content(blob))
    branch_date = validate_date(branch_index.get("updated_at"), today)
    candidate_for_date = deepcopy(candidate)
    candidate_for_date["updated_at"] = branch_date.isoformat()
    if branch_index != candidate_for_date:
        raise ValueError("既有分支 index.json 与候选内容不符")
    return base, head_sha, base_tree_sha


def create_branch(
    api: GitHub,
    base_tree_sha: str,
    base: str,
    branch: str,
    title: str,
    expected_main_sha: str,
    candidate: dict,
) -> None:
    require_main(api, expected_main_sha)
    blob = api.request(
        "POST",
        f"repos/{CENTRAL}/git/blobs",
        {
            "content": json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            "encoding": "utf-8",
        },
    )
    require_main(api, expected_main_sha)
    tree = api.request(
        "POST",
        f"repos/{CENTRAL}/git/trees",
        {
            "base_tree": base_tree_sha,
            "tree": [
                {
                    "path": "index.json",
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"],
                }
            ],
        },
    )
    require_main(api, expected_main_sha)
    commit = api.request(
        "POST",
        f"repos/{CENTRAL}/git/commits",
        {"message": title, "tree": tree["sha"], "parents": [base]},
    )
    require_main(api, expected_main_sha)
    api.request(
        "POST",
        f"repos/{CENTRAL}/git/refs",
        {"ref": f"refs/heads/{branch}", "sha": commit["sha"]},
    )


def create_or_resume_pr(
    api: GitHub,
    candidate: dict,
    plugin_id: str,
    version: str,
    expected_main_sha: str,
    expected_index_sha: str,
    verified_source_sha: str,
    today: date,
) -> str:
    branch = f"chore/{plugin_id}-v{version}"
    title = f"chore(index): {plugin_id} 升至 v{version}"
    open_target = find_target_pull(api, plugin_id, branch)
    base, head_sha, base_tree_sha = existing_branch(
        api, branch, expected_main_sha, expected_index_sha, candidate, today
    )
    if head_sha:
        if open_target:
            if open_target.get("head", {}).get("sha") != head_sha:
                raise ValueError("开放 PR 与目标分支 head 不一致")
            require_main(api, expected_main_sha)
            return str(open_target["html_url"])
    elif open_target:
        raise ValueError("开放 PR 的目标分支不存在")
    else:
        create_branch(
            api, base_tree_sha, base, branch, title, expected_main_sha, candidate
        )

    current_source_sha = resolve_tag_commit(
        api, PILOT[plugin_id], version, f"v{version}"
    )
    if current_source_sha != verified_source_sha:
        raise ValueError("Git tag 已移动，原已核验发布与当前 tag 不再匹配")
    require_main(api, expected_main_sha)
    pull = api.request(
        "POST",
        f"repos/{CENTRAL}/pulls",
        {
            "title": title,
            "head": branch,
            "base": "main",
            "body": "自动生成的社区索引版本更新。索引 ref 保持 main；请人工检查后合并。",
        },
    )
    if not isinstance(pull, dict) or not pull.get("html_url"):
        raise ValueError("PR 创建响应缺少 URL；分支保留，可安全重试")
    return pull["html_url"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--create-pr", action="store_true", help="显式创建更新分支与 PR"
    )
    args = parser.parse_args()
    try:
        api = GitHub()
        snapshot_sha = verify_snapshot(api)
        index_response = api.request(
            "GET", f"repos/{CENTRAL}/contents/index.json?ref={snapshot_sha}"
        )
        index = json.loads(decode_content(index_response))
        today = datetime.now(UTC).date()
        candidate = build_candidate(
            index, args.plugin_id, args.version, today.isoformat()
        )
        if candidate is None:
            print("索引版本已相同，无需更新")
            return 0
        plugin = next(item for item in index["plugins"] if item["id"] == args.plugin_id)
        repo = github_repo(plugin["repository"])
        commit = resolve_tag_commit(api, repo, args.version, args.tag)
        validate_release(api, repo, commit, args.version)
        validate_local(candidate, snapshot_sha)
        if not args.create_pr:
            print(
                f"dry-run: {args.plugin_id} {plugin['version']} → {args.version}; tag={args.tag}; commit={commit}; 无远端写入"
            )
            return 0
        if not isinstance(index_response, dict) or not SHA.fullmatch(
            str(index_response.get("sha", ""))
        ):
            raise ValueError("可信 index 响应缺少有效 blob SHA")
        print(
            create_or_resume_pr(
                api,
                candidate,
                args.plugin_id,
                args.version,
                snapshot_sha,
                index_response["sha"],
                commit,
                today,
            )
        )
        return 0
    except (
        ValueError,
        subprocess.CalledProcessError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"release_index_pr: 发布校验失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
