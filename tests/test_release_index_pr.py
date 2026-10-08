import base64
import contextlib
import io
import json
import subprocess
import unittest
from datetime import date
from unittest.mock import patch

from tools.release_index_pr import (
    CENTRAL,
    ROOT,
    build_candidate,
    create_or_resume_pr,
    github_repo,
    main,
    metadata_version,
    resolve_tag_commit,
    validate_date,
    validate_release,
    verify_snapshot,
)

SHA = "a" * 40
TAG_SHA = "b" * 40


class API:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        value = self.responses[(method, path)]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(data)
        return value


def content(text):
    return {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}


def release_api(tag_type="commit", ref="refs/tags/v0.3.0", version="0.3.0"):
    root = "TogetsuDo/pallas-plugin-memes"
    responses = {
        (
            "GET",
            "repos/PallasBot/community-plugin-index/contents/index.json?ref=main",
        ): content(
            json.dumps(
                {
                    "version": 1,
                    "updated_at": "old",
                    "plugins": [
                        {
                            "id": "memes",
                            "repository": f"https://github.com/{root}.git",
                            "ref": "main",
                            "version": "0.2.11",
                            "name": "x",
                        },
                        {
                            "id": "other",
                            "repository": "https://github.com/x/y",
                            "version": "1.0.0",
                        },
                    ],
                }
            )
        ),
        ("GET", f"repos/{root}/git/ref/tags/v{version}"): {
            "ref": ref,
            "object": {"type": tag_type, "sha": TAG_SHA if tag_type == "tag" else SHA},
        },
        ("GET", f"repos/{root}/git/commits/{SHA}"): {"sha": SHA},
        ("GET", f"repos/{root}/contents/community-index.entry.json?ref={SHA}"): content(
            json.dumps(
                {
                    "id": "memes",
                    "repository": f"https://github.com/{root}.git",
                    "ref": "main",
                    "version": version,
                }
            )
        ),
        ("GET", f"repos/{root}/contents/__init__.py?ref={SHA}"): content(
            f"__plugin_meta__ = PluginMetadata(extra={{'version': '{version}'}})"
        ),
        ("GET", f"repos/{root}/contents/CHANGELOG.md?ref={SHA}"): content(
            f"## [{version}] - 2026-10-08\n"
        ),
    }
    if tag_type == "tag":
        responses[("GET", f"repos/{root}/git/tags/{TAG_SHA}")] = {
            "object": {"type": "commit", "sha": SHA}
        }
    return API(responses)


class MainAPI:
    main_sha = "9" * 40
    index_sha = "8" * 40
    source_sha = "a" * 40

    def __init__(
        self, index=None, tag_ref="refs/tags/v0.3.0", move_main_after=None, pulls=None
    ):
        self.index = index or json.loads(
            (ROOT / "index.json").read_text(encoding="utf-8")
        )
        self.tag_ref = tag_ref
        self.move_main_after = move_main_after
        self.pulls = pulls or []
        self.main_reads = 0
        self.calls = []

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        source = "TogetsuDo/pallas-plugin-memes"
        if path.endswith("/contents/index.json?ref=" + self.main_sha):
            return {**content(json.dumps(self.index)), "sha": self.index_sha}
        if path.endswith("/git/ref/tags/v0.3.0"):
            return {
                "ref": self.tag_ref,
                "object": {"type": "commit", "sha": self.source_sha},
            }
        if path.endswith(f"/git/commits/{self.source_sha}"):
            return {"sha": self.source_sha}
        if path.endswith(f"/contents/community-index.entry.json?ref={self.source_sha}"):
            return content(
                json.dumps(
                    {
                        "id": "memes",
                        "repository": f"https://github.com/{source}.git",
                        "ref": "main",
                        "version": "0.3.0",
                    }
                )
            )
        if path.endswith(f"/contents/__init__.py?ref={self.source_sha}"):
            return content(
                "__plugin_meta__ = PluginMetadata(extra={'version': '0.3.0'})"
            )
        if path.endswith(f"/contents/CHANGELOG.md?ref={self.source_sha}"):
            return content("## [Unreleased]\n\n## [0.3.0] - 2026-10-08\n")
        if path.endswith("/pulls?state=all&per_page=100&page=1"):
            return self.pulls
        if path.endswith("/git/ref/heads/main"):
            self.main_reads += 1
            if self.move_main_after and self.main_reads >= self.move_main_after:
                return {"object": {"sha": "7" * 40}}
            return {"object": {"sha": self.main_sha}}
        if path.endswith(f"/git/commits/{self.main_sha}"):
            return {"tree": {"sha": "6" * 40}}
        if path.endswith("/git/trees/" + "6" * 40 + "?recursive=1"):
            return {
                "tree": [
                    {
                        "path": "index.json",
                        "mode": "100644",
                        "type": "blob",
                        "sha": self.index_sha,
                    }
                ]
            }
        if path.endswith("/git/ref/heads/chore/memes-v0.3.0"):
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 404: Not Found")
        if method == "POST" and path.endswith("/git/blobs"):
            return {"sha": "5" * 40}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": "4" * 40}
        if method == "POST" and path.endswith("/git/commits"):
            return {"sha": "3" * 40}
        if method == "POST" and path.endswith("/git/refs"):
            return {}
        if method == "POST" and path.endswith("/pulls"):
            return {
                "html_url": "https://github.com/PallasBot/community-plugin-index/pull/1"
            }
        raise AssertionError((method, path))


class ReleaseIndexPRTests(unittest.TestCase):
    def test_main_default_dry_run_uses_only_get_api_calls(self):
        api = MainAPI()
        with (
            patch("tools.release_index_pr.GitHub", return_value=api),
            patch("tools.release_index_pr.verify_snapshot", return_value=api.main_sha),
            patch(
                "sys.argv",
                [
                    "release_index_pr.py",
                    "--plugin-id",
                    "memes",
                    "--version",
                    "0.3.0",
                    "--tag",
                    "v0.3.0",
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(), 0)
        self.assertTrue(api.calls)
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))
        self.assertIn(
            f"repos/{CENTRAL}/contents/index.json?ref={api.main_sha}",
            [path for _, path, _ in api.calls],
        )

    def test_main_create_pr_happy_path_and_main_move_precheck_have_expected_writes(
        self,
    ):
        api = MainAPI()
        with (
            patch("tools.release_index_pr.GitHub", return_value=api),
            patch("tools.release_index_pr.verify_snapshot", return_value=api.main_sha),
            patch(
                "sys.argv",
                [
                    "release_index_pr.py",
                    "--plugin-id",
                    "memes",
                    "--version",
                    "0.3.0",
                    "--tag",
                    "v0.3.0",
                    "--create-pr",
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(), 0)
        writes = [(method, path) for method, path, _ in api.calls if method == "POST"]
        self.assertEqual(
            [path.rsplit("/", 1)[-1] for _, path in writes],
            ["blobs", "trees", "commits", "refs", "pulls"],
        )

        moved = MainAPI(move_main_after=2)
        with (
            patch("tools.release_index_pr.GitHub", return_value=moved),
            patch(
                "tools.release_index_pr.verify_snapshot", return_value=moved.main_sha
            ),
            patch(
                "sys.argv",
                [
                    "release_index_pr.py",
                    "--plugin-id",
                    "memes",
                    "--version",
                    "0.3.0",
                    "--tag",
                    "v0.3.0",
                    "--create-pr",
                ],
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(), 1)
        self.assertFalse(any(method == "POST" for method, _, _ in moved.calls))

    def test_fork_wrong_base_and_closed_merged_prs_do_not_contaminate(self):
        branch = "chore/memes-v0.3.0"
        pulls = [
            {
                "head": {"ref": branch, "repo": {"full_name": "someone/fork"}},
                "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
                "state": "open",
            },
            {
                "head": {"ref": branch, "repo": {"full_name": CENTRAL}},
                "base": {"ref": "dev", "repo": {"full_name": CENTRAL}},
                "state": "open",
            },
            {
                "head": {"ref": branch, "repo": {"full_name": CENTRAL}},
                "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
                "state": "closed",
                "merged_at": "2026-10-08T00:00:00Z",
            },
            {
                "head": {
                    "ref": "chore/memes-v0.4.0",
                    "repo": {"full_name": CENTRAL},
                },
                "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
                "state": "closed",
                "merged_at": None,
            },
        ]
        api = MainAPI(pulls=pulls)
        with (
            patch("tools.release_index_pr.GitHub", return_value=api),
            patch("tools.release_index_pr.verify_snapshot", return_value=api.main_sha),
            patch(
                "sys.argv",
                [
                    "release_index_pr.py",
                    "--plugin-id",
                    "memes",
                    "--version",
                    "0.3.0",
                    "--tag",
                    "v0.3.0",
                    "--create-pr",
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(), 0)
        self.assertIn(
            ("POST", f"repos/{CENTRAL}/pulls"),
            [(method, path) for method, path, _ in api.calls],
        )

    def test_main_equal_version_invalid_tag_and_real_validator_failure_do_not_write(
        self,
    ):
        cases = [
            (MainAPI(), "0.2.11", "v0.2.11", 0),
            (MainAPI(tag_ref="refs/tags/not-the-tag"), "0.3.0", "v0.3.0", 1),
        ]
        for api, version, tag, expected_exit in cases:
            with self.subTest(version=version, tag=tag):
                with (
                    patch("tools.release_index_pr.GitHub", return_value=api),
                    patch(
                        "tools.release_index_pr.verify_snapshot",
                        return_value=api.main_sha,
                    ),
                    patch(
                        "sys.argv",
                        [
                            "release_index_pr.py",
                            "--plugin-id",
                            "memes",
                            "--version",
                            version,
                            "--tag",
                            tag,
                            "--create-pr",
                        ],
                    ),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(main(), expected_exit)
                self.assertFalse(any(method == "POST" for method, _, _ in api.calls))

        class MissingIndex(MainAPI):
            def request(self, method, path, data=None):
                if path.endswith("/contents/index.json?ref=" + self.main_sha):
                    self.calls.append((method, path, data))
                    raise subprocess.CalledProcessError(
                        1, "gh", stderr="HTTP 404: Not Found"
                    )
                return super().request(method, path, data)

        api = MissingIndex()
        with (
            patch("tools.release_index_pr.GitHub", return_value=api),
            patch("tools.release_index_pr.verify_snapshot", return_value=api.main_sha),
            patch(
                "sys.argv",
                [
                    "release_index_pr.py",
                    "--plugin-id",
                    "memes",
                    "--version",
                    "0.3.0",
                    "--tag",
                    "v0.3.0",
                    "--create-pr",
                ],
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(), 1)
        self.assertFalse(any(method == "POST" for method, _, _ in api.calls))

        invalid_index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
        invalid_index["plugins"].append(dict(invalid_index["plugins"][0]))
        api = MainAPI(index=invalid_index)
        with (
            patch("tools.release_index_pr.GitHub", return_value=api),
            patch("tools.release_index_pr.verify_snapshot", return_value=api.main_sha),
            patch(
                "sys.argv",
                [
                    "release_index_pr.py",
                    "--plugin-id",
                    "memes",
                    "--version",
                    "0.3.0",
                    "--tag",
                    "v0.3.0",
                    "--create-pr",
                ],
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(), 1)
        self.assertFalse(any(method == "POST" for method, _, _ in api.calls))

    def test_snapshot_rejects_moving_main_and_dirty_gate_file(self):
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()

        class SnapshotAPI:
            def __init__(self, sha):
                self.sha, self.calls = sha, []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                return {"object": {"sha": self.sha}}

        api = SnapshotAPI(head)
        self.assertEqual(verify_snapshot(api), head)
        api = SnapshotAPI("7" * 40)
        with self.assertRaises(ValueError):
            verify_snapshot(api)

        api = SnapshotAPI(head)
        run = subprocess.run

        def dirty_read(args, **kwargs):
            if args[:2] == ["git", "show"] and args[2].endswith(":README.md"):
                return subprocess.CompletedProcess(args, 0, stdout=b"dirty")
            return run(args, **kwargs)

        with (
            patch("tools.release_index_pr.subprocess.run", side_effect=dirty_read),
            self.assertRaises(ValueError),
        ):
            verify_snapshot(api)

    def test_annotated_and_lightweight_tag_and_three_version_sources(self):
        for kind in ("commit", "tag"):
            api = release_api(kind)
            commit = resolve_tag_commit(
                api, "TogetsuDo/pallas-plugin-memes", "0.3.0", "v0.3.0"
            )
            self.assertEqual(commit, SHA)
            validate_release(api, "TogetsuDo/pallas-plugin-memes", SHA, "0.3.0")

    def test_wrong_ref_or_type_and_annotated_cycle_rejected(self):
        api = release_api("tree")
        with self.assertRaises(ValueError):
            resolve_tag_commit(api, "TogetsuDo/pallas-plugin-memes", "0.3.0", "v0.3.0")

    def test_metadata_ast_requires_single_explicit_literal_declaration(self):
        good = (
            "__plugin_meta__ = PluginMetadata(extra={'name': 'x', 'version': '0.3.0'})"
        )
        self.assertEqual(metadata_version(good), "0.3.0")
        invalid = (
            "__plugin_meta__ = Other(extra={'version': '0.3.0'})",
            "__plugin_meta__ = PluginMetadata(extra={'version': '0.3.0', 'version': '0.3.0'})",
            "__plugin_meta__ = PluginMetadata(extra={'version': '0.3.0'}, extra={'x': 1})",
            "__plugin_meta__ = PluginMetadata(extra={**BASE, 'version': '0.3.0'})",
            "__plugin_meta__ = PluginMetadata(**META)",
            "__plugin_meta__ = PluginMetadata(extra={'version': VERSION})",
            good + "\n__plugin_meta__ = PluginMetadata(extra={'version': '0.3.0'})",
            good + "\n__plugin_meta__ = Other()",
            "if flag:\n    __plugin_meta__ = PluginMetadata(extra={'version': '0.3.0'})",
            good + "\ndel __plugin_meta__",
            good + "\n__plugin_meta__.extra['version'] = '0.3.1'",
            good + "\ndel __plugin_meta__.extra['version']",
            "__plugin_meta__: object = PluginMetadata(extra={'version': '0.3.0'})",
        )
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(ValueError):
                metadata_version(source)
        api = release_api("tag")
        api.responses[
            ("GET", f"repos/TogetsuDo/pallas-plugin-memes/git/tags/{TAG_SHA}")
        ] = {"object": {"type": "tag", "sha": TAG_SHA}}
        with self.assertRaises(ValueError):
            resolve_tag_commit(api, "TogetsuDo/pallas-plugin-memes", "0.3.0", "v0.3.0")

    def test_repository_url_rejects_abnormal_path_or_origin(self):
        self.assertEqual(
            github_repo("https://github.com/TogetsuDo/pallas-plugin-memes.git"),
            "TogetsuDo/pallas-plugin-memes",
        )
        for url in (
            "https://github.com.evil/a/b",
            "https://github.com/a/b/",
            "https://github.com/a/b?x=1",
            "git@github.com:a/b.git",
        ):
            with self.assertRaises(ValueError):
                github_repo(url)
        api = release_api()
        api.responses[
            ("GET", "repos/TogetsuDo/pallas-plugin-memes/git/ref/tags/v0.3.0")
        ]["ref"] = "refs/tags/other"
        with self.assertRaises(ValueError):
            resolve_tag_commit(api, "TogetsuDo/pallas-plugin-memes", "0.3.0", "v0.3.0")

    def test_all_release_metadata_versions_must_match(self):
        api = release_api()
        api.responses[
            (
                "GET",
                "repos/TogetsuDo/pallas-plugin-memes/contents/__init__.py?ref=" + SHA,
            )
        ] = content("__plugin_meta__ = PluginMetadata(extra={'version': '0.3.1'})")
        with self.assertRaises(ValueError):
            validate_release(api, "TogetsuDo/pallas-plugin-memes", SHA, "0.3.0")

    def test_upgrade_changes_only_version_and_date(self):
        index = {
            "updated_at": "old",
            "plugins": [
                {
                    "id": "memes",
                    "version": "0.2.11",
                    "repository": "https://github.com/TogetsuDo/pallas-plugin-memes.git",
                    "ref": "main",
                    "name": "x",
                },
                {"id": "other", "version": "1.0.0"},
            ],
        }
        candidate = build_candidate(index, "memes", "0.3.0", "2026-10-08")
        self.assertEqual(candidate["updated_at"], "2026-10-08")
        self.assertEqual(
            candidate["plugins"][0],
            {
                "id": "memes",
                "version": "0.3.0",
                "repository": "https://github.com/TogetsuDo/pallas-plugin-memes.git",
                "ref": "main",
                "name": "x",
            },
        )
        self.assertEqual(candidate["plugins"][1], index["plugins"][1])

    def test_equal_and_downgrade(self):
        index = {
            "updated_at": "old",
            "plugins": [
                {
                    "id": "memes",
                    "version": "0.2.11",
                    "repository": "https://github.com/TogetsuDo/pallas-plugin-memes.git",
                }
            ],
        }
        self.assertIsNone(build_candidate(index, "memes", "0.2.11", "2026-10-08"))
        with self.assertRaises(ValueError):
            build_candidate(index, "memes", "0.2.10", "2026-10-08")

    def test_existing_date_must_be_canonical_iso_and_not_future(self):
        self.assertEqual(
            validate_date("2026-10-08", date(2026, 10, 8)), date(2026, 10, 8)
        )
        for value in ("20261008", "2026-10-09", "not-a-date"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_date(value, date(2026, 10, 8))

    def test_unknown_id_and_version_injection_rejected(self):
        index = {
            "plugins": [
                {
                    "id": "memes",
                    "version": "0.2.11",
                    "repository": "https://github.com/TogetsuDo/pallas-plugin-memes.git",
                }
            ]
        }
        for plugin_id, version in (("unknown", "0.3.0"), ("memes", "0.3.0;gh")):
            with self.assertRaises(ValueError):
                build_candidate(index, plugin_id, version, "2026-10-08")

    def test_pr_failure_retry_only_completes_pull_request(self):
        candidate = {
            "updated_at": "2026-10-08",
            "plugins": [{"id": "memes", "version": "0.3.0"}],
        }
        base, commit, tree = "c" * 40, "d" * 40, "e" * 40

        class RetryAPI:
            def __init__(self):
                self.branch_exists = False
                self.failed_pull = False
                self.pull_open = False
                self.calls = []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                if path.endswith("/pulls?state=all&per_page=100&page=1"):
                    if self.pull_open:
                        return [
                            {
                                "state": "open",
                                "head": {
                                    "ref": "chore/memes-v0.3.0",
                                    "sha": commit,
                                    "repo": {"full_name": CENTRAL},
                                },
                                "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
                                "html_url": "https://github.com/PallasBot/community-plugin-index/pull/1",
                            }
                        ]
                    return []
                if path.endswith("/git/ref/heads/main"):
                    return {"object": {"sha": base}}
                if path.endswith("/git/ref/heads/chore/memes-v0.3.0"):
                    if not self.branch_exists:
                        raise subprocess.CalledProcessError(
                            1, "gh", stderr="HTTP 404: Not Found"
                        )
                    return {"object": {"sha": commit}}
                if path.endswith(f"/git/commits/{base}"):
                    return {"sha": base, "tree": {"sha": "f" * 40}}
                if path.endswith(f"/git/commits/{commit}"):
                    return {
                        "sha": commit,
                        "tree": {"sha": tree},
                        "parents": [{"sha": base}],
                    }
                if path.endswith("/git/trees/" + "f" * 40 + "?recursive=1"):
                    return {
                        "tree": [
                            {
                                "path": "index.json",
                                "sha": "1" * 40,
                                "mode": "100644",
                                "type": "blob",
                            }
                        ]
                    }
                if path.endswith(f"/git/trees/{tree}?recursive=1"):
                    return {
                        "tree": [
                            {
                                "path": "index.json",
                                "sha": "2" * 40,
                                "mode": "100644",
                                "type": "blob",
                            }
                        ]
                    }
                if path.endswith(f"/contents/index.json?ref={commit}"):
                    return content(json.dumps(candidate))
                if method == "POST" and path.endswith("/git/blobs"):
                    return {"sha": "2" * 40}
                if method == "POST" and path.endswith("/git/trees"):
                    return {"sha": tree}
                if method == "POST" and path.endswith("/git/commits"):
                    return {"sha": commit}
                if method == "POST" and path.endswith("/git/refs"):
                    self.branch_exists = True
                    return {}
                if method == "POST" and path.endswith("/pulls"):
                    if not self.failed_pull:
                        self.failed_pull = True
                        raise subprocess.CalledProcessError(1, "gh")
                    self.pull_open = True
                    return {
                        "html_url": "https://github.com/PallasBot/community-plugin-index/pull/1"
                    }
                raise AssertionError((method, path))

        api = RetryAPI()
        with self.assertRaises(subprocess.CalledProcessError):
            create_or_resume_pr(
                api, candidate, "memes", "0.3.0", base, "1" * 40, date(2026, 10, 8)
            )
        before = len(api.calls)
        url = create_or_resume_pr(
            api,
            {**candidate, "updated_at": "2026-10-09"},
            "memes",
            "0.3.0",
            base,
            "1" * 40,
            date(2026, 10, 9),
        )
        self.assertTrue(url.endswith("/pull/1"))
        retry_calls = api.calls[before:]
        self.assertFalse(
            any(
                path.endswith(("/git/blobs", "/git/trees", "/git/commits", "/git/refs"))
                and method == "POST"
                for method, path, _ in retry_calls
            )
        )
        before = len(api.calls)
        url = create_or_resume_pr(
            api,
            {**candidate, "updated_at": "2026-10-10"},
            "memes",
            "0.3.0",
            base,
            "1" * 40,
            date(2026, 10, 10),
        )
        self.assertTrue(url.endswith("/pull/1"))
        self.assertFalse(any(method == "POST" for method, _, _ in api.calls[before:]))

    def test_other_open_pr_and_stale_manual_branch_rejected_without_writes(self):
        candidate = {
            "updated_at": "2026-10-08",
            "plugins": [{"id": "memes", "version": "0.3.0"}],
        }

        class ConflictAPI:
            def __init__(self, pulls, branch=False):
                self.pulls, self.branch, self.calls = pulls, branch, []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                if path.endswith("/pulls?state=all&per_page=100&page=1"):
                    return self.pulls
                if path.endswith("/git/ref/heads/main"):
                    return {"object": {"sha": "c" * 40}}
                if path.endswith("/git/commits/" + "c" * 40):
                    return {"tree": {"sha": "f" * 40}}
                if path.endswith("/git/trees/" + "f" * 40 + "?recursive=1"):
                    return {
                        "tree": [
                            {
                                "path": "index.json",
                                "sha": "1" * 40,
                                "mode": "100644",
                                "type": "blob",
                            }
                        ]
                    }
                if path.endswith("/git/ref/heads/chore/memes-v0.3.0"):
                    if not self.branch:
                        raise subprocess.CalledProcessError(
                            1, "gh", stderr="HTTP 404: Not Found"
                        )
                    return {"object": {"sha": "d" * 40}}
                if path.endswith("/git/commits/" + "d" * 40):
                    return {"parents": [{"sha": "e" * 40}]}
                raise AssertionError(path)

        other = ConflictAPI(
            [
                {
                    "head": {
                        "ref": "chore/memes-v0.4.0",
                        "repo": {"full_name": CENTRAL},
                    },
                    "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
                    "state": "open",
                    "html_url": "url",
                }
            ]
        )
        with self.assertRaises(ValueError):
            create_or_resume_pr(
                other,
                candidate,
                "memes",
                "0.3.0",
                "c" * 40,
                "1" * 40,
                date(2026, 10, 8),
            )
        stale = ConflictAPI([], branch=True)
        with self.assertRaises(ValueError):
            create_or_resume_pr(
                stale,
                candidate,
                "memes",
                "0.3.0",
                "c" * 40,
                "1" * 40,
                date(2026, 10, 8),
            )
        self.assertFalse(
            any(
                method == "POST" for api in (other, stale) for method, _, _ in api.calls
            )
        )

    def test_gitlink_mode_change_and_multiple_parents_rejected_without_writes(self):
        base, branch, base_tree, branch_tree = "c" * 40, "d" * 40, "e" * 40, "f" * 40
        candidate = {
            "updated_at": "2026-10-08",
            "plugins": [{"id": "memes", "version": "0.3.0"}],
        }

        class TreeAPI:
            def __init__(self, leaves, parents):
                self.leaves, self.parents, self.calls = leaves, parents, []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                if path.endswith("/pulls?state=all&per_page=100&page=1"):
                    return []
                if path.endswith("/git/ref/heads/main"):
                    return {"object": {"sha": base}}
                if path.endswith(f"/git/commits/{base}"):
                    return {"tree": {"sha": base_tree}}
                if path.endswith(f"/git/trees/{base_tree}?recursive=1"):
                    return {
                        "tree": [
                            {
                                "path": "index.json",
                                "sha": "1" * 40,
                                "mode": "100644",
                                "type": "blob",
                            }
                        ]
                    }
                if path.endswith("/git/ref/heads/chore/memes-v0.3.0"):
                    return {"object": {"sha": branch}}
                if path.endswith(f"/git/commits/{branch}"):
                    return {
                        "parents": [{"sha": base} for _ in self.parents],
                        "tree": {"sha": branch_tree},
                    }
                if path.endswith(f"/git/trees/{branch_tree}?recursive=1"):
                    return {"tree": self.leaves}
                raise AssertionError((method, path))

        bad_trees = (
            [
                {
                    "path": "index.json",
                    "sha": "2" * 40,
                    "mode": "100644",
                    "type": "blob",
                },
                {"path": "vendor", "sha": "3" * 40, "mode": "160000", "type": "commit"},
            ],
            [{"path": "index.json", "sha": "1" * 40, "mode": "100755", "type": "blob"}],
        )
        cases = [(leaves, [base]) for leaves in bad_trees] + [
            (bad_trees[0], [base, "9" * 40])
        ]
        for leaves, parents in cases:
            api = TreeAPI(leaves, parents)
            with self.assertRaises(ValueError):
                create_or_resume_pr(
                    api, candidate, "memes", "0.3.0", base, "1" * 40, date(2026, 10, 8)
                )
            self.assertFalse(any(method == "POST" for method, _, _ in api.calls))

    def test_pull_pagination_finds_page_two_conflict(self):
        base = "c" * 40
        irrelevant = [
            {
                "head": {
                    "ref": f"chore/other-{i}",
                    "repo": {"full_name": "someone/fork"},
                },
                "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
                "state": "open",
            }
            for i in range(100)
        ]
        target = {
            "head": {"ref": "chore/memes-v0.4.0", "repo": {"full_name": CENTRAL}},
            "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
            "state": "open",
        }

        class Pages:
            def __init__(self):
                self.calls = []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                if path.endswith("page=1"):
                    return irrelevant
                if path.endswith("page=2"):
                    return [target]
                raise AssertionError(path)

        api = Pages()
        with self.assertRaises(ValueError):
            create_or_resume_pr(
                api,
                {"updated_at": "2026-10-08"},
                "memes",
                "0.3.0",
                base,
                "1" * 40,
                date(2026, 10, 8),
            )
        self.assertEqual(len(api.calls), 2)

    def test_pull_target_filter_rejects_forks_and_non_main_bases(self):
        from tools.release_index_pr import pull_belongs_to_central_main

        valid = {
            "head": {"repo": {"full_name": "pallasbot/community-plugin-index"}},
            "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
        }
        self.assertTrue(pull_belongs_to_central_main(valid))
        fork = {
            **valid,
            "head": {"repo": {"full_name": "someone/community-plugin-index"}},
        }
        wrong_base = {**valid, "base": {"ref": "dev", "repo": {"full_name": CENTRAL}}}
        for pull in (fork, wrong_base):
            self.assertFalse(pull_belongs_to_central_main(pull))

    def test_real_closed_unmerged_target_pr_is_rejected_without_writes(self):
        target = {
            "head": {"ref": "chore/memes-v0.3.0", "repo": {"full_name": CENTRAL}},
            "base": {"ref": "main", "repo": {"full_name": CENTRAL}},
            "state": "closed",
            "merged_at": None,
        }

        class ClosedAPI:
            def __init__(self):
                self.calls = []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                if path.endswith("/pulls?state=all&per_page=100&page=1"):
                    return [target]
                raise AssertionError(path)

        api = ClosedAPI()
        with self.assertRaisesRegex(ValueError, "未合并关闭 PR"):
            create_or_resume_pr(
                api, {}, "memes", "0.3.0", "c" * 40, "1" * 40, date(2026, 10, 8)
            )
        self.assertFalse(any(method == "POST" for method, _, _ in api.calls))


if __name__ == "__main__":
    unittest.main()
