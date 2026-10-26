#!/usr/bin/env python3
"""Merge class of a pull request in a xippios SDK repository: ``auto`` or ``human``.

The rules, in order (README.md, "Merge classes"). Every rule is evaluated and every reason
collected; the first ``human`` decides the class, the later ones only add to the summary.

1. Scaffold, in a source repository only (``sdk-*`` other than sdk-core and sdk-template):
   the base has no ``src/`` directory.
2. Render trust: a changed file the template owns (rendered, and matched by no
   ``_skip_if_exists`` pattern) that is byte-identical to the template rendered at the
   head's ``_commit`` with the head's answers leaves the changed set. The render runs at
   the SHA ``_commit`` resolves to on the template's main. A render that fails trusts
   nothing. A change to ``.copier-answers.yml`` other than ``_commit`` moving forward
   along the template's main, ``core_version`` or ``core_git_ref`` is the session's:
   ``human``.
3. Protected paths in what remains; in a source, also a template-owned file under
   ``src/`` that differs from the render (an adapter changed by hand); in sdk-template,
   the template origin of every path protected in a source, any path under ``template/``
   with Jinja in its name, and the dependency block of ``template/pyproject.toml.jinja``;
   in ``xippios/.github`` every pull request.
4. First surface: a ``src/xippios/**/tasks.py`` whose ``__all__`` was empty or absent
   names at least one task.
5. Release: the ``[project]`` version of ``pyproject.toml`` changed, and what remains is
   not a subset of the release files.
6. Otherwise ``auto``.

"Base" for rule 1 is the base commit itself; every comparison of content (the changed set,
rules 3 to 5) is against the merge base of base and head, which is the base itself once a
pull request is up to date with its branch.

Standard library only, so a workflow runs it with the runner's ``python3``; the render
calls ``uvx copier``. Nothing from the pull request is executed: its files are read as git
objects, and git clone, uv and copier run in a temporary directory outside the checkout.

Exit status: 0 for ``auto``, 1 for ``human``, 2 when the classification itself failed.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

AUTO = "auto"
HUMAN = "human"

DEFAULT_TEMPLATE_URL = "https://github.com/xippios/sdk-template.git"
# The template's _commit is trusted only when it is on this branch of the template.
TEMPLATE_BRANCH = "main"
COPIER_SPEC = "copier>=9,<10"
RENDER_TIMEOUT = 900  # seconds, for the template clone and for the render each
ANSWERS_FILE = ".copier-answers.yml"
# The answers a pull request changes without a human: _commit moving forward along the
# template's main (checked against the template), and the core pins.
FREE_ANSWERS = frozenset({"_commit", "core_version", "core_git_ref"})

PROTECTED = (
    ".github/**",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/agents/**",
    ".claude/hooks/**",
    ".mcp.json",
    "CLAUDE.local.md",
    ".pre-commit-config.yaml",
    ".secrets.baseline",
    "docs/conventions.md",
    "docs/adr/**",
    "docs/review-checklist.md",
    "docs/definition-of-done.md",
)
# Protected in a source only. The template renders them, so rule 2 trusts them when they
# are identical to the render, and they are human when changed by hand.
SOURCE_PROTECTED = (".claude/commands/**",)
TEMPLATE_DIR = "template/"


def template_origins(patterns: Iterable[str]) -> tuple[str, ...]:
    """Where the template renders a protected source path from: ``template/``, ``.jinja``."""
    origins: list[str] = []
    for pattern in patterns:
        origins.append(TEMPLATE_DIR + pattern)
        if not pattern.endswith("/**"):
            origins.append(f"{TEMPLATE_DIR}{pattern}.jinja")
    return tuple(origins)


PROTECTED_BY_REPO: dict[str, tuple[str, ...]] = {
    "sdk-core": ("src/**",),
    # What is protected in a source is protected at its template origin.
    "sdk-template": (
        "copier.yml",
        "copier.yaml",
        "scripts/**",
        *template_origins(PROTECTED + SOURCE_PROTECTED),
    ),
}
# In sdk-template, protected when its dependency block changes.
TEMPLATE_PYPROJECT = "template/pyproject.toml.jinja"
# Template-owned modules under src/ by name, for when no render tells which files the
# template owns (--no-render, a failed render).
ADAPTER_MODULES = re.compile(r"src/xippios/(?:.+/)?(?:mcp|http|_version|api/__init__)\.py")
# Every pull request of the organisation's .github repository is human.
ORG_REPOSITORY = ".github"
# The repositories named sdk-* that are not sources; rule 1 skips them.
FAMILY_REPOSITORIES = frozenset({"sdk-core", "sdk-template"})

RELEASE_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "CHANGELOG.md",
        "README.md",
        "CLAUDE.md",
        "docs/handover.md",
        "scripts/check-siblings.sh",
    }
)
TASKS_MODULE = re.compile(r"src/xippios/(?:.+/)?tasks\.py")
REGULAR_FILE_MODES = frozenset({"100644", "100755"})


class ClassifyError(RuntimeError):
    """The classification could not be computed (a git failure, a bad revision)."""


class RenderError(RuntimeError):
    """The template could not be rendered or its settings not read; nothing is trusted."""


Renderer = Callable[[str, str, Path, Path], None]
"""``renderer(template_url, vcs_ref, data_file, dest)`` renders the template into ``dest``."""


@dataclass
class Finding:
    """One rule's result: ``human`` findings decide the class, the others are notes."""

    rule: int
    text: str
    human: bool = True


@dataclass
class Classification:
    """The class of one pull request and how it was reached."""

    repo: str
    base: str
    head: str
    merge_base: str
    changed: list[str]
    trusted: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    template_ref: str | None = None
    template_sha: str | None = None

    @property
    def merge_class(self) -> str:
        """``human`` when any rule says so, else ``auto``."""
        return HUMAN if any(f.human for f in self.findings) else AUTO


# --- git ---------------------------------------------------------------------------------


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LITERAL_PATHSPECS"] = "1"
    return env


def _git(workdir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        ["git", "-C", str(workdir), *args],
        capture_output=True,
        check=False,
        env=_env(),
        timeout=RENDER_TIMEOUT,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise ClassifyError(f"git {' '.join(args)} failed: {detail}")
    return proc


def resolve(workdir: Path, rev: str) -> str:
    """The commit SHA ``rev`` names in ``workdir``."""
    proc = _git(workdir, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
    if proc.returncode != 0:
        raise ClassifyError(f"{rev!r} is not a commit in {workdir}")
    return proc.stdout.decode().strip()


def merge_base(workdir: Path, base: str, head: str) -> str:
    """The merge base of ``base`` and ``head``; ``base`` when they share no history."""
    proc = _git(workdir, "merge-base", base, head, check=False)
    return proc.stdout.decode().strip() if proc.returncode == 0 else base


def changed_files(workdir: Path, old: str, new: str) -> list[str]:
    """Every path that differs between two commits; a rename counts as both of its paths."""
    out = _git(
        workdir,
        "diff",
        "--name-only",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        "-z",
        old,
        new,
    ).stdout.decode()
    return sorted(p for p in out.split("\0") if p)


def tree_entry(workdir: Path, rev: str, path: str) -> tuple[str, str, str] | None:
    """``(mode, type, object)`` of ``path`` at ``rev``, or None when it does not exist."""
    out = _git(workdir, "ls-tree", "-z", "--full-tree", rev, "--", path).stdout.decode()
    for record in out.split("\0"):
        if not record:
            continue
        meta, _, name = record.partition("\t")
        if name == path:
            mode, kind, obj = meta.split()
            return mode, kind, obj
    return None


def read_blob(workdir: Path, rev: str, path: str) -> bytes | None:
    """The content of the regular file ``path`` at ``rev``, or None when there is none."""
    entry = tree_entry(workdir, rev, path)
    if entry is None or entry[1] != "blob" or entry[0] not in REGULAR_FILE_MODES:
        return None
    return _git(workdir, "cat-file", "blob", entry[2]).stdout


# --- patterns ----------------------------------------------------------------------------


def _segment_regex(segment: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(segment):
        char = segment[i]
        if char == "\\" and i + 1 < len(segment):
            out.append(re.escape(segment[i + 1]))
            i += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = segment.find("]", i + 2)
            if end == -1:
                out.append(re.escape(char))
            else:
                body = segment[i + 1 : end].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = end + 1
                continue
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class IgnorePattern:
    """One gitignore-style pattern, the semantics copier gives ``_skip_if_exists``."""

    regex: re.Pattern[str]
    dir_only: bool


def compile_pattern(pattern: str) -> IgnorePattern | None:
    """Compile one gitignore-style pattern; None for blanks, comments and negations.

    Negations are dropped on purpose: a larger skip set trusts fewer files.
    """
    text = pattern.strip()
    if not text or text.startswith(("#", "!")):
        return None
    dir_only = text.endswith("/")
    text = text.rstrip("/")
    if not text:
        return None
    anchored = "/" in text
    segments = text.lstrip("/").split("/")
    parts = [] if anchored else ["(?:.+/)?"]
    need_slash = False
    last = len(segments) - 1
    for i, segment in enumerate(segments):
        if segment == "**":
            if i == 0 and i == last:
                parts.append(".+")
                need_slash = True
            elif i == 0:
                parts.append("(?:.+/)?")
                need_slash = False
            elif i == last:
                parts.append("/.+")
                need_slash = True
            else:
                parts.append("(?:/.+)?")
                need_slash = True
        else:
            if need_slash:
                parts.append("/")
            parts.append(_segment_regex(segment))
            need_slash = True
    return IgnorePattern(re.compile("".join(parts)), dir_only)


def matches_any(path: str, patterns: Iterable[IgnorePattern]) -> bool:
    """Whether ``path`` or one of its parent directories matches a pattern."""
    parts = path.split("/")
    candidates = [("/".join(parts[:k]), True) for k in range(1, len(parts))]
    candidates.append((path, False))
    for pattern in patterns:
        for candidate, is_dir in candidates:
            if pattern.dir_only and not is_dir:
                continue
            if pattern.regex.fullmatch(candidate):
                return True
    return False


def is_protected(path: str, pattern: str) -> bool:
    """Root-anchored match of a protected-path pattern (``dir/**`` or an exact path)."""
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return path == pattern


# --- YAML subsets (stdlib only) ----------------------------------------------------------

_TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return re.sub(r"\s+#.*$", "", value)


def answer_entries(text: str) -> list[tuple[str | None, list[str]]]:
    """The top-level entries of a copier answers file, each with its lines.

    Comment and blank lines before the first key form an entry with key None.
    """
    entries: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        match = _TOP_KEY.match(line)
        if match:
            entries.append((match.group(1), [line]))
        else:
            entries[-1][1].append(line)
    return entries


def answer_scalar(entries: Sequence[tuple[str | None, list[str]]], key: str) -> str | None:
    """The plain or quoted scalar value of ``key``, or None when absent or not a scalar."""
    for name, lines in entries:
        if name != key:
            continue
        value = lines[0].split(":", 1)[1].strip()
        continuation = [line for line in lines[1:] if line.strip() and not line.startswith("#")]
        if not value or continuation or value[0] in "|>[{&*!":
            return None
        return _unquote(value)
    return None


def _text(source: bytes) -> str:
    """Decode a file for comparison; undecodable bytes stay distinct (surrogate escapes)."""
    return source.decode("utf-8", errors="surrogateescape")


def answer_table(source: bytes | None) -> dict[str, list[str]]:
    """Each top-level answer's lines by key, comments and blank lines left out."""
    table: dict[str, list[str]] = {}
    if source is None:
        return table
    for key, lines in answer_entries(_text(source)):
        if key is None:
            continue
        kept = [line.rstrip() for line in lines if line.strip() and line.lstrip()[:1] != "#"]
        table.setdefault(key, []).extend(kept)
    return table


def answers_commit(source: bytes | None) -> str | None:
    """The ``_commit`` of an answers file, or None when absent or not a scalar."""
    return answer_scalar(answer_entries(_text(source)), "_commit") if source is not None else None


def answer_changes(before: bytes | None, after: bytes | None, forward: bool | None) -> list[str]:
    """Rule 2's human reasons for a change to the answers file.

    ``forward`` says whether the head's ``_commit`` descends from the base's on the
    template's main: None when the template could not be checked (``--no-render``, a
    failed clone, a ``_commit`` the render refused), which leaves any change human.
    """
    old, new = answer_table(before), answer_table(after)
    keys = sorted(k for k in (old.keys() | new.keys()) - FREE_ANSWERS if old.get(k) != new.get(k))
    reasons = [f"answers changed: {', '.join(keys)}"] if keys else []
    if old.get("_commit") != new.get("_commit"):
        old_commit, new_commit = answers_commit(before), answers_commit(after)
        if (old_commit is None or old_commit != new_commit) and forward is not True:
            how = (
                "not forward along the template's main"
                if forward is False
                else "not checked against the template"
            )
            reasons.append(
                f"_commit changes from {old_commit or 'none'} to {new_commit or 'none'}, {how}"
            )
    return reasons


def answers_data(entries: Sequence[tuple[str | None, list[str]]]) -> str:
    """The answers without ``_commit`` and ``_src_path``, for ``copier copy --data-file``."""
    kept = [
        line for name, lines in entries if name not in {"_commit", "_src_path"} for line in lines
    ]
    return "\n".join(kept) + "\n"


def skip_patterns(copier_yml: str) -> list[str]:
    """The ``_skip_if_exists`` list of a copier.yml, unrendered."""
    lines = copier_yml.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^_skip_if_exists\s*:(.*)$", line)
        if not match:
            continue
        rest = re.sub(r"\s+#.*$", "", match.group(1)).strip()
        if rest.startswith("[") and rest.endswith("]"):
            return [_unquote(item) for item in rest[1:-1].split(",") if item.strip()]
        if rest:
            raise RenderError(f"_skip_if_exists is not a list: {rest!r}")
        patterns: list[str] = []
        for item in lines[i + 1 :]:
            stripped = item.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not stripped.startswith("- ") and stripped != "-":
                break
            patterns.append(_unquote(stripped[1:]))
        return patterns
    raise RenderError("copier.yml has no _skip_if_exists")


# --- file content rules ------------------------------------------------------------------


def _names(node: ast.expr) -> list[str] | None:
    if isinstance(node, ast.List | ast.Tuple) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts
    ):
        return [e.value for e in node.elts if isinstance(e, ast.Constant)]
    return None


def _is_all(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "__all__"


def _modifies_all(node: ast.AST) -> bool:
    """Whether ``node`` assigns, deletes or calls a method of ``__all__`` anywhere inside."""
    for inner in ast.walk(node):
        if (
            isinstance(inner, ast.Name)
            and inner.id == "__all__"
            and isinstance(inner.ctx, ast.Store | ast.Del)
        ):
            return True
        if (
            isinstance(inner, ast.Subscript | ast.Attribute)
            and _is_all(inner.value)
            and isinstance(inner.ctx, ast.Store | ast.Del)
        ):
            return True
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and _is_all(inner.func.value)
        ):
            return True
    return False


def exported_names(source: bytes | None) -> list[str] | None:
    """The names in a module's literal ``__all__``.

    ``[]`` when the module or its ``__all__`` is absent; None when ``__all__`` cannot be
    read statically: assigned something other than a literal list or tuple of strings,
    or changed by a call or inside another statement.
    """
    if source is None:
        return []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(_is_all(t) for t in targets):
                if _modifies_all(node):
                    return None
                continue
            if not all(isinstance(t, ast.Name) for t in targets):
                return None
            if node.value is None:  # a bare annotation
                continue
            literal = _names(node.value)
            if literal is None:
                return None
            if isinstance(node, ast.AugAssign):
                if not isinstance(node.op, ast.Add):
                    return None
                names = [*names, *literal]
            else:
                names = literal
        elif _modifies_all(node):
            return None
    return names


_TABLE = re.compile(r"^\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$")
_ARRAY_TABLE = re.compile(r"^\[\[\s*([^\[\]]+?)\s*\]\]\s*(?:#.*)?$")
_KEY = re.compile(r"^([A-Za-z0-9_.\"' -]+?)\s*=(.*)$")
# The dependency block of a pyproject: these tables and keys, and everything below them.
DEPENDENCY_NAMES = (
    "project.dependencies",
    "project.optional-dependencies",
    "dependency-groups",
    "tool.uv.sources",
)


def _toml_name(text: str) -> str:
    return ".".join(part.strip().strip("\"'") for part in text.split("."))


def _in_dependency_block(name: str) -> bool:
    return any(name == top or name.startswith(top + ".") for top in DEPENDENCY_NAMES)


def _nesting(text: str) -> int:
    return text.count("[") + text.count("{") - text.count("]") - text.count("}")


def dependency_block(text: str | None) -> list[str] | None:
    """The dependency block of a pyproject template, as stripped lines with their table.

    Read as text, since a Jinja template is not TOML: ``[project] dependencies``,
    ``[project.optional-dependencies]``, ``[dependency-groups]`` and ``[tool.uv.sources]``,
    whether written as tables, as dotted keys or as multi-line values, Jinja lines included.
    """
    if text is None:
        return None
    block: list[str] = []
    table = ""
    depth = 0
    keep = False
    for raw in text.splitlines():
        line = raw.strip()
        if depth > 0:
            if keep:
                block.append(f"{table}: {line}")
            depth += _nesting(line)
            continue
        header = _TABLE.match(line) or _ARRAY_TABLE.match(line)
        if header:
            table = _toml_name(header.group(1))
            continue
        if _in_dependency_block(table):
            if line:
                block.append(f"{table}: {line}")
            depth = max(_nesting(line), 0)
            keep = True
            continue
        key = _KEY.match(line)
        if key:
            name = _toml_name(f"{table}.{key.group(1)}" if table else key.group(1))
            keep = _in_dependency_block(name)
            if keep:
                block.append(f"{table}: {line}")
            depth = max(_nesting(key.group(2)), 0)
    return block


def project_version(source: bytes | None) -> str | None:
    """The ``[project] version`` of a pyproject.toml; None when absent."""
    if source is None:
        return None
    data = tomllib.loads(source.decode())
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    return str(version) if version is not None else None


# --- render trust ------------------------------------------------------------------------


def normalize_url(url: str) -> str:
    """One spelling per template location, for comparing ``_src_path`` with the template."""
    text = url.strip()
    if text.startswith("gh:"):
        text = "https://github.com/" + text[3:]
    elif text.startswith("git@github.com:"):
        text = "https://github.com/" + text[len("git@github.com:") :]
    elif text.startswith("git+https://"):
        text = text[len("git+") :]
    text = text.rstrip("/").removesuffix(".git")
    if text.lower().startswith("https://github.com/"):
        text = text.lower()
    return text


def copier_render(template_url: str, vcs_ref: str, data_file: Path, dest: Path) -> None:
    """Render the template with ``uvx copier copy``, outside any checkout."""
    uvx = shutil.which("uvx")
    if uvx is None:
        raise RenderError("uvx is not on PATH")
    cmd = [
        uvx,
        "--no-config",
        "--quiet",
        "--from",
        COPIER_SPEC,
        "copier",
        "copy",
        "--defaults",
        "--trust",
        "--skip-tasks",
        "--quiet",
        "--vcs-ref",
        vcs_ref,
        "--data-file",
        str(data_file),
        template_url,
        str(dest),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=dest.parent,
            capture_output=True,
            text=True,
            check=False,
            env=_env(),
            timeout=RENDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"copier timed out after {RENDER_TIMEOUT} s") from exc
    if proc.returncode != 0:
        tail = " ".join(proc.stderr.strip().splitlines()[-3:])
        raise RenderError(f"copier exited {proc.returncode}: {tail}")


def _clone_template(template_url: str, scratch: Path) -> Path:
    """A bare-bones clone of the template (no checkout), with its tags and its main."""
    clone = scratch / "template"
    try:
        proc = subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", "--", template_url, str(clone)],
            cwd=scratch,
            capture_output=True,
            check=False,
            env=_env(),
            timeout=RENDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"cloning {template_url} timed out") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise RenderError(f"cannot clone {template_url}: {detail}")
    return clone


def _on_main(clone: Path, commit: str) -> str:
    """The SHA ``commit`` names in the template, which must be on the template's main."""
    try:
        sha = resolve(clone, commit)
    except ClassifyError as exc:
        raise RenderError(f"_commit {commit!r} is not a commit of the template") from exc
    branch = f"refs/remotes/origin/{TEMPLATE_BRANCH}"
    if _git(clone, "merge-base", "--is-ancestor", sha, branch, check=False).returncode != 0:
        raise RenderError(f"_commit {commit!r} is not on the template's {TEMPLATE_BRANCH}")
    return sha


def _skip_list(clone: Path, sha: str) -> list[str]:
    """The ``_skip_if_exists`` patterns of the template's copier.yml at ``sha``."""
    for name in ("copier.yml", "copier.yaml"):
        content = read_blob(clone, sha, name)
        if content is not None:
            return skip_patterns(content.decode())
    raise RenderError(f"the template has no copier.yml at {sha}")


# A tag, a SHA or `git describe` output; never an option.
_GIT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/-]*")


@dataclass
class Trust:
    """The outcome of rule 2."""

    trusted: list[str]
    template_ref: str | None
    note: str | None
    template_sha: str | None = None
    # Whether the head's _commit descends from the base's on the template's main; None
    # when unchanged or not checked.
    commit_forward: bool | None = None
    # The changed paths the template owns (rendered, skip-listed by no pattern); None
    # when there was no render to tell.
    owned: list[str] | None = None


def _moves_forward(clone: Path, old: str, new_sha: str) -> bool:
    """Whether the template commit ``old`` is an ancestor of ``new_sha``."""
    if not _GIT_REF.fullmatch(old):
        return False
    try:
        old_sha = resolve(clone, old)
    except ClassifyError:
        return False
    return _git(clone, "merge-base", "--is-ancestor", old_sha, new_sha, check=False).returncode == 0


def trust_rendered(
    workdir: Path,
    head: str,
    changed: Sequence[str],
    template_url: str,
    renderer: Renderer,
    base_commit: str | None = None,
) -> Trust:
    """Rule 2: the changed template-owned files that are byte-identical to the render.

    ``base_commit`` is the base's ``_commit``; when the head's differs, the template clone
    also tells whether it moved forward.
    """
    answers = read_blob(workdir, head, ANSWERS_FILE)
    if answers is None:
        return Trust([], None, f"no {ANSWERS_FILE} on the head; nothing is trusted")
    try:
        entries = answer_entries(answers.decode())
    except UnicodeDecodeError:
        return Trust([], None, f"{ANSWERS_FILE} is not UTF-8; nothing is trusted")
    commit = answer_scalar(entries, "_commit")
    src_path = answer_scalar(entries, "_src_path")
    import_path = answer_scalar(entries, "import_path")
    if not commit or not src_path or not import_path:
        note = f"{ANSWERS_FILE} lacks _commit, _src_path or import_path; nothing trusted"
        return Trust([], commit, note)
    if not _GIT_REF.fullmatch(commit):
        return Trust([], commit, f"_commit {commit!r} is not a plain git ref; nothing trusted")
    if normalize_url(src_path) != normalize_url(template_url):
        note = f"_src_path {src_path} is not the family template {template_url}; nothing trusted"
        return Trust([], commit, note)
    with tempfile.TemporaryDirectory(prefix="merge-class-") as tmp:
        scratch = Path(tmp)
        forward: bool | None = None
        try:
            clone = _clone_template(template_url, scratch)
            sha = _on_main(clone, commit)
            if base_commit is not None and base_commit != commit:
                forward = _moves_forward(clone, base_commit, sha)
            raw_patterns = _skip_list(clone, sha)
            package_dir = import_path.replace(".", "/")
            rendered_patterns = [
                re.sub(r"\{\{\s*package_dir\s*\}\}", package_dir, p) for p in raw_patterns
            ]
            unresolved = [p for p in rendered_patterns if "{{" in p or "{%" in p]
            if unresolved:
                raise RenderError(f"_skip_if_exists keeps Jinja after substitution: {unresolved}")
            patterns = [c for c in map(compile_pattern, rendered_patterns) if c is not None]
            data_file = scratch / "answers.yml"
            data_file.write_text(answers_data(entries))
            dest = scratch / "render"
            # The SHA checked above, never the ref name: a tag or branch could move between
            # the check and copier's own clone.
            renderer(template_url, sha, data_file, dest)
        except RenderError as exc:
            note = f"render failed, nothing is trusted: {exc}"
            return Trust([], commit, note, commit_forward=forward)
        trusted: list[str] = []
        owned: list[str] = []
        for path in changed:
            if matches_any(path, patterns):
                continue  # filled by the session; never trusted
            rendered = dest / path
            if rendered.is_symlink() or not rendered.is_file():
                continue  # the template does not render it
            owned.append(path)
            ours = read_blob(workdir, head, path)
            if ours is not None and rendered.read_bytes() == ours:
                trusted.append(path)
    return Trust(trusted, commit, None, sha, forward, owned)


# --- classification ----------------------------------------------------------------------


def _repo_name(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1]


def is_source(name: str) -> bool:
    """Whether a repository is a source: named ``sdk-*``, and not sdk-core or sdk-template."""
    return name.startswith("sdk-") and name not in FAMILY_REPOSITORIES


def classify(
    *,
    repo: str,
    base: str,
    head: str,
    workdir: Path,
    render: bool = True,
    template_url: str = DEFAULT_TEMPLATE_URL,
    renderer: Renderer = copier_render,
) -> Classification:
    """Classify the pull request from ``base`` to ``head`` of ``repo`` in ``workdir``."""
    base_sha = resolve(workdir, base)
    head_sha = resolve(workdir, head)
    fork = merge_base(workdir, base_sha, head_sha)
    changed = changed_files(workdir, fork, head_sha)
    result = Classification(repo, base_sha, head_sha, fork, changed)
    name = _repo_name(repo)
    add = result.findings.append

    # 1. Scaffold, sources only: sdk-template and .github have no src/ at all
    if is_source(name):
        entry = tree_entry(workdir, base_sha, "src")
        if entry is None or entry[1] != "tree":
            add(Finding(1, "scaffold: the base has no src/ directory"))

    # 2. Render trust, and the answers file
    before_answers = read_blob(workdir, fork, ANSWERS_FILE)
    after_answers = read_blob(workdir, head_sha, ANSWERS_FILE)
    if render:
        base_commit = answers_commit(before_answers)
        trust = trust_rendered(workdir, head_sha, changed, template_url, renderer, base_commit)
    else:
        trust = Trust([], None, "render skipped (--no-render); nothing is trusted")
    result.trusted = trust.trusted
    result.template_ref = trust.template_ref
    result.template_sha = trust.template_sha
    if trust.note:
        add(Finding(2, trust.note, human=False))
    # Over the changed set, not what remains: the render writes the answers back as they are.
    if ANSWERS_FILE in changed:
        for reason in answer_changes(before_answers, after_answers, trust.commit_forward):
            add(Finding(2, reason))
    remaining = [p for p in changed if p not in set(trust.trusted)]
    result.remaining = remaining

    # 3. Protected paths
    if name == ORG_REPOSITORY:
        add(Finding(3, f"every pull request of {repo} is human"))
    protected = PROTECTED + PROTECTED_BY_REPO.get(name, ())
    if is_source(name):
        protected += SOURCE_PROTECTED
    for path in remaining:
        hits = [p for p in protected if is_protected(path, p)]
        if hits:
            add(Finding(3, f"protected path {path} (matches {hits[0]})"))
            continue
        # An adapter changed by hand could expose tasks around rule 4.
        if is_source(name) and path.startswith("src/"):
            if trust.owned is not None and path in trust.owned:
                add(Finding(3, f"{path} is template-owned and differs from the render"))
            elif trust.owned is None and ADAPTER_MODULES.fullmatch(path):
                add(Finding(3, f"{path} is template-owned and no render could compare it"))
        # Jinja in a name can render to any path, a protected one included.
        jinja = "{{" in path or "{%" in path
        if name == "sdk-template" and path.startswith(TEMPLATE_DIR) and jinja:
            add(Finding(3, f"{path} carries Jinja in its name under {TEMPLATE_DIR}"))
    if name == "sdk-template" and TEMPLATE_PYPROJECT in remaining:
        before = read_blob(workdir, fork, TEMPLATE_PYPROJECT)
        after = read_blob(workdir, head_sha, TEMPLATE_PYPROJECT)
        old = dependency_block(before.decode() if before is not None else None)
        new = dependency_block(after.decode() if after is not None else None)
        if old != new:
            add(Finding(3, f"the dependency block of {TEMPLATE_PYPROJECT} changed"))

    # 4. First surface
    for path in remaining:
        if not TASKS_MODULE.fullmatch(path):
            continue
        before_names = exported_names(read_blob(workdir, fork, path))
        after_names = exported_names(read_blob(workdir, head_sha, path))
        if before_names is None or after_names is None:
            add(Finding(4, f"cannot read __all__ of {path} statically"))
        elif not before_names and after_names:
            add(Finding(4, f"first surface: {path} exports {', '.join(after_names)}"))

    # 5. Release
    if "pyproject.toml" in changed:
        try:
            old_version = project_version(read_blob(workdir, fork, "pyproject.toml"))
            new_version = project_version(read_blob(workdir, head_sha, "pyproject.toml"))
        except ValueError as exc:  # TOMLDecodeError and UnicodeDecodeError
            add(Finding(5, f"cannot read the version in pyproject.toml: {exc}"))
        else:
            if old_version != new_version:
                outside = [p for p in remaining if p not in RELEASE_FILES]
                if outside:
                    add(
                        Finding(
                            5,
                            f"release {old_version} -> {new_version} also changes "
                            + ", ".join(outside),
                        )
                    )
    return result


# --- output ------------------------------------------------------------------------------

_RULE_NAMES = {
    1: "scaffold",
    2: "render trust",
    3: "protected paths",
    4: "first surface",
    5: "release",
}


def summary_markdown(result: Classification) -> str:
    """The job summary: class, rules hit, trusted files, remaining changed files."""
    lines = [
        f"## merge-class: `{result.merge_class}`",
        "",
        (
            f"`{result.repo}`: base `{result.base[:12]}`, head `{result.head[:12]}`, "
            f"merge base `{result.merge_base[:12]}`; {len(result.changed)} changed files."
        ),
        "",
        "### Rules hit",
        "",
    ]
    if result.findings:
        for finding in result.findings:
            effect = "human" if finding.human else "note"
            name = _RULE_NAMES[finding.rule]
            lines.append(f"- rule {finding.rule} ({name}, {effect}): {finding.text}")
    if not any(f.human for f in result.findings):
        lines.append("- rule 6: no rule says human, so `auto`")
    ref = f" at `{result.template_ref}`" if result.template_ref else ""
    if result.template_sha:
        ref += f" (`{result.template_sha[:12]}`)"
    lines += ["", f"### Trusted: byte-identical to the template{ref} ({len(result.trusted)})", ""]
    lines += [f"- `{p}`" for p in result.trusted] or ["- none"]
    lines += ["", f"### Remaining changed files ({len(result.remaining)})", ""]
    lines += [f"- `{p}`" for p in result.remaining] or ["- none"]
    return "\n".join(lines) + "\n"


def report_text(result: Classification) -> str:
    """The plain-text report printed to stdout."""
    lines = [f"class={result.merge_class}"]
    for finding in result.findings:
        effect = "human" if finding.human else "note"
        lines.append(f"rule {finding.rule} ({effect}): {finding.text}")
    ref = f" at {result.template_ref}" if result.template_ref else ""
    if result.template_sha:
        ref += f" ({result.template_sha[:12]})"
    lines.append(f"trusted{ref} ({len(result.trusted)}): {', '.join(result.trusted) or '-'}")
    lines.append(f"remaining ({len(result.remaining)}): {', '.join(result.remaining) or '-'}")
    return "\n".join(lines)


def _append(path: str | None, text: str) -> None:
    if path:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(text)


def main(argv: Sequence[str] | None = None) -> int:
    """Command line entry point; the exit status is the class (0 auto, 1 human, 2 error)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo", required=True, help="owner/name of the pull request's repository")
    parser.add_argument("--base", required=True, help="the base commit (SHA or revision)")
    parser.add_argument("--head", required=True, help="the head commit (SHA or revision)")
    parser.add_argument(
        "--workdir", required=True, type=Path, help="a git checkout containing both commits"
    )
    parser.add_argument(
        "--summary",
        default=os.environ.get("GITHUB_STEP_SUMMARY"),
        help="markdown summary appended here (default $GITHUB_STEP_SUMMARY)",
    )
    parser.add_argument(
        "--no-render", action="store_true", help="skip the render of rule 2; nothing is trusted"
    )
    parser.add_argument(
        "--template-url", default=DEFAULT_TEMPLATE_URL, help="the family template's git URL"
    )
    args = parser.parse_args(argv)
    output = os.environ.get("GITHUB_OUTPUT")
    try:
        result = classify(
            repo=args.repo,
            base=args.base,
            head=args.head,
            workdir=args.workdir,
            render=not args.no_render,
            template_url=args.template_url,
        )
    except (ClassifyError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"class={HUMAN}\nmerge-class failed: {exc}", file=sys.stderr)
        _append(output, f"class={HUMAN}\n")
        _append(args.summary, f"## merge-class: classification failed\n\n{exc}\n")
        return 2
    print(report_text(result))
    _append(output, f"class={result.merge_class}\n")
    _append(args.summary, summary_markdown(result))
    return 1 if result.merge_class == HUMAN else 0


if __name__ == "__main__":
    sys.exit(main())
