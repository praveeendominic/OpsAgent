"""Offline tests for the repository tools, bound to the bundled orders-api sample."""
from __future__ import annotations

import subprocess
import sys

import pytest

from opsagent.config import PROJECT_ROOT
from opsagent.tools.repo_tools import (
    RecentCommitsTool,
    RepoContext,
    RepoGrepTool,
    RepoListTool,
    RepoPathError,
    RepoReadTool,
    make_repo_tools,
)

SAMPLE = PROJECT_ROOT / "examples" / "orders-api"


@pytest.fixture(scope="module")
def tools() -> dict[str, object]:
    return {t.name: t for t in make_repo_tools(SAMPLE)}


def test_factory_builds_four_named_tools(tools):
    assert set(tools) == {"repo_list_files", "repo_read_file", "repo_grep", "repo_recent_commits"}
    for t in tools.values():
        assert "orders-api" in t.description, t.name


def test_list_includes_cache_module(tools):
    out = tools["repo_list_files"].run()
    assert "app/orders/cache.py" in out
    assert "app/leak_demo.py" in out
    assert "__pycache__" not in out
    assert ".git/" not in out


def test_list_with_subdir_and_pattern(tools):
    out = tools["repo_list_files"].run(subdir="app/orders", pattern="*.py")
    assert "app/orders/cache.py" in out
    assert "app/main.py" not in out


def test_grep_finds_log_message(tools):
    out = tools["repo_grep"].run(pattern="order cache grew")
    assert "leak_demo.py" in out or "cache.py" in out
    assert ":" in out  # path:line: text


def test_grep_finds_defect_symbol_with_context(tools):
    out = tools["repo_grep"].run(pattern=r"ORDER_CACHE\[", context=3)
    assert "app/orders/cache.py" in out
    assert "def remember" in out  # context lines above the insert reach the def


def test_grep_invalid_regex_is_reported_not_raised(tools):
    out = tools["repo_grep"].run(pattern="(unclosed")
    assert out.startswith("invalid regular expression")


def test_read_returns_numbered_lines_with_defect(tools):
    out = tools["repo_read_file"].run(path="app/orders/cache.py")
    assert "ORDER_CACHE" in out
    assert "def remember" in out
    # numbered-line format: "<n>| text"
    assert any(line.lstrip().split("|")[0].strip().isdigit() for line in out.splitlines()[1:3])


def test_read_caps_window(tools):
    out = tools["repo_read_file"].run(path="app/main.py", start_line=1, end_line=5000)
    body = [ln for ln in out.splitlines()[1:] if "|" in ln]
    assert len(body) <= 300


@pytest.mark.parametrize(
    "bad",
    ["../../.env", "../.env", "app/../../.env", "/etc/passwd", "C:/Windows/win.ini", r"C:\Windows\win.ini", "//server/share"],
)
def test_traversal_and_absolute_paths_are_rejected(tools, bad):
    out = tools["repo_read_file"].run(path=bad)
    assert out.startswith("refused:"), out
    assert "repository root" in out or "absolute" in out


def test_ignored_directories_are_refused(tools):
    out = tools["repo_read_file"].run(path=".git/config")
    assert out.startswith("refused:")


def test_context_resolve_raises_for_escape():
    ctx = RepoContext(root=SAMPLE)
    with pytest.raises(RepoPathError):
        ctx.resolve("../../pyproject.toml")


def test_symlink_is_not_followed(tmp_path):
    (tmp_path / "ok.txt").write_text("fine\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}_outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this host")
    tool = RepoReadTool(repo=RepoContext(root=tmp_path))
    out = tool.run(path="link.txt")
    assert out.startswith("refused:") and "symlink" in out
    assert "link.txt" not in RepoListTool(repo=RepoContext(root=tmp_path)).run()


def test_binary_files_are_refused(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    out = RepoReadTool(repo=RepoContext(root=tmp_path)).run(path="blob.bin")
    assert out.startswith("refused:") and "binary" in out


def test_recent_commits_returns_string(tools):
    out = tools["repo_recent_commits"].run(days=30)
    assert isinstance(out, str) and out
    assert out.startswith("no git history available") or "commit(s)" in out


def test_recent_commits_never_fails_hard(tmp_path):
    out = RecentCommitsTool(repo=RepoContext(root=tmp_path)).run()
    assert out.startswith("no git history available")


def test_sample_app_tests_pass():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(SAMPLE / "tests"), "-q", "-p", "no:cacheprovider"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
