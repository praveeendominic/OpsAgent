"""Read-only, size-capped CrewAI tools for inspecting an application repository.

All tools are bound to one `RepoContext` (a repository root on disk). Every path an agent
supplies is resolved inside that root; anything that escapes it (absolute paths, `..`,
drive letters, symlinks) is refused with a readable message instead of an exception so the
agent can correct itself. Only text files are returned, and `.git`, `__pycache__`,
`node_modules` and `.venv` are never listed, read or searched.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, Iterator

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from opsagent.schemas.code_correlation import RecentCommit

IGNORED_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv"})
BINARY_SNIFF_BYTES = 8_192
MAX_READ_LINES = 300
MAX_READ_BYTES = 20 * 1024
MAX_GREP_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_CHARS = 24_000
GIT_TIMEOUT_S = 15


class RepoPathError(ValueError):
    """Raised when a requested path is not a readable text file inside the repository."""


# ----------------------------------------------------------------------------- context


@dataclass(frozen=True)
class RepoContext:
    """The repository a set of tools is bound to."""

    root: Path
    display_name: str = ""

    def __post_init__(self) -> None:
        root = Path(self.root).resolve()
        object.__setattr__(self, "root", root)
        if not self.display_name:
            object.__setattr__(self, "display_name", root.name or str(root))

    # -- path safety ------------------------------------------------------------
    def resolve(self, rel: str, *, must_exist: bool = True) -> Path:
        """Resolve a repository-relative path. Refuses anything that leaves the root."""
        raw = (rel or "").strip().replace("\\", "/")
        if raw in ("", "."):
            return self.root
        pure = PurePosixPath(raw)
        if pure.is_absolute() or re.match(r"^[A-Za-z]:", raw) or raw.startswith("//"):
            raise RepoPathError(f"refused: absolute paths are not allowed, use a path relative to the {self.display_name} repository root")
        if any(part == ".." for part in pure.parts):
            raise RepoPathError(f"refused: '{rel}' escapes the {self.display_name} repository root ('..' is not allowed)")
        if any(part in IGNORED_DIRS for part in pure.parts):
            raise RepoPathError(f"refused: '{rel}' is inside an ignored directory ({', '.join(sorted(IGNORED_DIRS))})")

        candidate = self.root
        for part in pure.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise RepoPathError(f"refused: '{rel}' goes through a symlink, which is not followed")
        resolved = candidate.resolve()
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise RepoPathError(f"refused: '{rel}' resolves outside the {self.display_name} repository root")
        if must_exist and not resolved.exists():
            raise RepoPathError(f"not found: '{rel}' does not exist in the {self.display_name} repository")
        return resolved

    def relpath(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    # -- enumeration --------------------------------------------------------------
    def iter_files(self, subdir: str = "", pattern: str = "**/*") -> Iterator[Path]:
        """Yield regular text-candidate files under `subdir` matching `pattern`, sorted."""
        base = self.resolve(subdir)
        if not base.is_dir():
            raise RepoPathError(f"not a directory: '{subdir}'")
        pattern = (pattern or "**/*").replace("\\", "/").lstrip("/")
        if ".." in PurePosixPath(pattern).parts:
            raise RepoPathError("refused: '..' is not allowed in glob patterns")
        seen: set[Path] = set()
        for p in sorted(base.glob(pattern)):
            if p in seen:
                continue
            seen.add(p)
            try:
                rel_parts = p.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part in IGNORED_DIRS for part in rel_parts):
                continue
            if p.is_symlink() or not p.is_file():
                continue
            yield p


# ----------------------------------------------------------------------------- helpers


def _is_text_file(p: Path) -> bool:
    try:
        with p.open("rb") as fh:
            chunk = fh.read(BINARY_SNIFF_BYTES)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    return True


def _read_text(p: Path, limit: int | None = None) -> str:
    with p.open("rb") as fh:
        data = fh.read(limit) if limit else fh.read()
    return data.decode("utf-8", errors="replace")


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _cap_output(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... output truncated at {MAX_OUTPUT_CHARS} characters; narrow the request."


def find_git_root(start: Path) -> Path | None:
    """Walk upwards from `start` to the first directory containing `.git`."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def collect_recent_commits(ctx: RepoContext, days: int = 14, path: str = "", max_commits: int = 20) -> list[RecentCommit]:
    """Run `git log` for the repository (or the enclosing git repo, limited to the subpath).

    Returns an empty list on any failure; callers decide how to describe that.
    """
    git_root = find_git_root(ctx.root)
    if git_root is None:
        return []
    target = ctx.resolve(path, must_exist=False) if path else ctx.root
    try:
        pathspec = target.relative_to(git_root).as_posix()
    except ValueError:
        pathspec = "."
    if pathspec in ("", "."):
        pathspec = "."
    days = max(1, int(days))
    max_commits = max(1, min(int(max_commits), 200))
    cmd = [
        "git",
        "-C",
        str(git_root),
        "log",
        f"--since={days}.days",
        f"--max-count={max_commits}",
        "--name-only",
        "--date=iso",
        "--format=%x1e%H%x1f%ad%x1f%s",
        "--",
        pathspec,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []

    commits: list[RecentCommit] = []
    for chunk in proc.stdout.split("\x1e"):
        chunk = chunk.strip("\r\n")
        if not chunk.strip():
            continue
        header, _, rest = chunk.partition("\n")
        parts = header.split("\x1f")
        if len(parts) < 3:
            continue
        sha, date, message = parts[0].strip(), parts[1].strip(), "\x1f".join(parts[2:]).strip()
        files = [ln.strip().replace("\\", "/") for ln in rest.splitlines() if ln.strip()]
        commits.append(RecentCommit(sha=sha, date=date, message=message, files=files))
    return commits


# ----------------------------------------------------------------------------- arg schemas


class ListArgs(BaseModel):
    subdir: str = Field(default="", description="directory relative to the repository root ('' for the root)")
    pattern: str = Field(default="**/*", description="glob pattern relative to subdir, e.g. '**/*.py'")
    max_files: int = Field(default=200, ge=1, le=1000, description="maximum number of files to list")


class ReadArgs(BaseModel):
    path: str = Field(description="file path relative to the repository root")
    start_line: int = Field(default=1, ge=1, description="first line to return (1-based)")
    end_line: int = Field(default=200, ge=1, description="last line to return (inclusive); at most 300 lines per call")


class GrepArgs(BaseModel):
    pattern: str = Field(description="Python regular expression to search for (case-sensitive unless you add (?i))")
    glob: str = Field(default="**/*.py", description="glob of files to search, relative to the repository root")
    max_results: int = Field(default=50, ge=1, le=500, description="maximum number of matching lines")
    context: int = Field(default=2, ge=0, le=10, description="lines of context before and after each match")


class CommitsArgs(BaseModel):
    days: int = Field(default=14, ge=1, le=3650, description="look back this many days")
    path: str = Field(default="", description="limit to this file or directory relative to the repository root")
    max_commits: int = Field(default=20, ge=1, le=200, description="maximum number of commits")


# ----------------------------------------------------------------------------- tools


class _RepoTool(BaseTool):
    """Common base: carries the bound RepoContext and turns path errors into readable text."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo: RepoContext
    name: str = ""
    description: str = ""

    _DESCRIPTION_TEMPLATE: ClassVar[str] = ""

    def __init__(self, repo: RepoContext, **kwargs: Any) -> None:
        kwargs.setdefault("description", self._DESCRIPTION_TEMPLATE.format(repo=repo.display_name, root=repo.root))
        super().__init__(repo=repo, **kwargs)

    def _run(self, **kwargs: Any) -> str:
        try:
            return _cap_output(self._run_safe(**kwargs))
        except RepoPathError as exc:
            return str(exc)
        except Exception as exc:  # never let the agent loop crash on a tool
            return f"error: {type(exc).__name__}: {exc}"

    def _run_safe(self, **kwargs: Any) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


class RepoListTool(_RepoTool):
    name: str = "repo_list_files"
    args_schema: type[BaseModel] = ListArgs
    _DESCRIPTION_TEMPLATE: ClassVar[str] = (
        "List text files in the '{repo}' repository (bound to {root}). Returns one line per file: "
        "'relative/path (size)'. Use subdir and pattern (glob, e.g. '**/*.py') to narrow the listing. "
        ".git, __pycache__, node_modules and .venv are never listed."
    )

    def _run_safe(self, subdir: str = "", pattern: str = "**/*", max_files: int = 200) -> str:
        lines: list[str] = []
        total = 0
        for p in self.repo.iter_files(subdir, pattern):
            if not _is_text_file(p):
                continue
            total += 1
            if len(lines) < max_files:
                lines.append(f"{self.repo.relpath(p)} ({_human_size(p.stat().st_size)})")
        if not lines:
            return f"no text files match pattern '{pattern}' under '{subdir or '.'}' in the {self.repo.display_name} repository"
        header = f"{total} file(s) in {self.repo.display_name}" + (f", showing first {max_files}" if total > max_files else "")
        return header + ":\n" + "\n".join(lines)


class RepoReadTool(_RepoTool):
    name: str = "repo_read_file"
    args_schema: type[BaseModel] = ReadArgs
    _DESCRIPTION_TEMPLATE: ClassVar[str] = (
        "Read a text file from the '{repo}' repository (bound to {root}) as numbered lines. "
        "Give a path relative to the repository root and an optional start_line/end_line window; "
        "at most 300 lines or 20 KB are returned per call, so page through large files."
    )

    def _run_safe(self, path: str, start_line: int = 1, end_line: int = 200) -> str:
        p = self.repo.resolve(path)
        if not p.is_file():
            raise RepoPathError(f"not a file: '{path}'")
        if not _is_text_file(p):
            raise RepoPathError(f"refused: '{path}' looks like a binary file")
        start = max(1, int(start_line))
        end = max(start, int(end_line))
        if end - start + 1 > MAX_READ_LINES:
            end = start + MAX_READ_LINES - 1
        text = _read_text(p)
        all_lines = text.splitlines()
        total = len(all_lines)
        if start > total:
            return f"{self.repo.relpath(p)}: file has {total} line(s); start_line {start} is past the end"
        out: list[str] = []
        used = 0
        truncated_bytes = False
        last = start - 1
        for i in range(start, min(end, total) + 1):
            line = all_lines[i - 1]
            entry = f"{i:>5}| {line}"
            if used + len(entry) + 1 > MAX_READ_BYTES:
                truncated_bytes = True
                break
            out.append(entry)
            used += len(entry) + 1
            last = i
        header = f"{self.repo.relpath(p)} lines {start}-{last} of {total}"
        footer = ""
        if last < total:
            reason = "20 KB cap reached" if truncated_bytes else "window end"
            footer = f"\n... {total - last} more line(s) after line {last} ({reason}); call again with start_line={last + 1}"
        return header + "\n" + "\n".join(out) + footer


class RepoGrepTool(_RepoTool):
    name: str = "repo_grep"
    args_schema: type[BaseModel] = GrepArgs
    _DESCRIPTION_TEMPLATE: ClassVar[str] = (
        "Search text files in the '{repo}' repository (bound to {root}) with a regular expression. "
        "Returns 'path:line: text' for each match with surrounding context lines (marked 'path-line- text'). "
        "Use glob to choose files (default '**/*.py'); good first searches are log message strings and symbol names."
    )

    def _run_safe(self, pattern: str, glob: str = "**/*.py", max_results: int = 50, context: int = 2) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"invalid regular expression '{pattern}': {exc}"
        results: list[str] = []
        matches = 0
        files_with_matches = 0
        scanned = 0
        for p in self.repo.iter_files("", glob):
            if p.stat().st_size > MAX_GREP_FILE_BYTES or not _is_text_file(p):
                continue
            scanned += 1
            lines = _read_text(p).splitlines()
            rel = self.repo.relpath(p)
            hit_in_file = False
            for idx, line in enumerate(lines, start=1):
                if not rx.search(line):
                    continue
                if not hit_in_file:
                    files_with_matches += 1
                    hit_in_file = True
                matches += 1
                if matches > max_results:
                    break
                lo = max(1, idx - context)
                hi = min(len(lines), idx + context)
                block = []
                for j in range(lo, hi + 1):
                    marker = ":" if j == idx else "-"
                    block.append(f"{rel}{marker}{j}{marker} {lines[j - 1]}")
                results.append("\n".join(block))
            if matches > max_results:
                break
        if matches == 0:
            return f"no matches for /{pattern}/ in {scanned} file(s) matching '{glob}' in the {self.repo.display_name} repository"
        shown = min(matches, max_results)
        header = f"{shown} match(es) for /{pattern}/ in {files_with_matches} file(s) of {self.repo.display_name}"
        if matches > max_results:
            header += f" (stopped at max_results={max_results}; more exist)"
        return header + "\n--\n" + "\n--\n".join(results)


class RecentCommitsTool(_RepoTool):
    name: str = "repo_recent_commits"
    args_schema: type[BaseModel] = CommitsArgs
    _DESCRIPTION_TEMPLATE: ClassVar[str] = (
        "List recent git commits touching the '{repo}' repository (bound to {root}): sha, date, message and "
        "changed files. Optionally limit to a path and a number of days. Returns 'no git history available' "
        "when the repository has no usable git history."
    )

    def _run_safe(self, days: int = 14, path: str = "", max_commits: int = 20) -> str:
        if path:
            self.repo.resolve(path, must_exist=False)  # validate even though git does the lookup
        commits = collect_recent_commits(self.repo, days=days, path=path, max_commits=max_commits)
        if not commits:
            scope = f" for '{path}'" if path else ""
            return f"no git history available{scope} in the last {days} day(s) for the {self.repo.display_name} repository"
        out = [f"{len(commits)} commit(s) in the last {days} day(s) touching {self.repo.display_name}{(' / ' + path) if path else ''}:"]
        for c in commits:
            out.append(f"- {c.sha[:10]}  {c.date}  {c.message}")
            for f in c.files[:25]:
                out.append(f"    {f}")
            if len(c.files) > 25:
                out.append(f"    ... {len(c.files) - 25} more file(s)")
        return "\n".join(out)


# ----------------------------------------------------------------------------- factory


def make_repo_tools(repo_root: Path, display_name: str = "") -> list[BaseTool]:
    """Build the four repository tools bound to `repo_root`."""
    ctx = RepoContext(root=Path(repo_root), display_name=display_name)
    if not ctx.root.is_dir():
        raise FileNotFoundError(f"repository root does not exist: {ctx.root}")
    return [RepoListTool(repo=ctx), RepoReadTool(repo=ctx), RepoGrepTool(repo=ctx), RecentCommitsTool(repo=ctx)]


__all__ = [
    "RepoContext",
    "RepoPathError",
    "RepoListTool",
    "RepoReadTool",
    "RepoGrepTool",
    "RecentCommitsTool",
    "make_repo_tools",
    "collect_recent_commits",
    "find_git_root",
]
