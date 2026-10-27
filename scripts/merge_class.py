#!/usr/bin/env python3
"""Merge class of a pull request in a xippios SDK repository: ``auto`` or ``human``.

The rules, in order (README.md, "Merge classes"). Every rule is evaluated and every reason
collected; the first ``human`` decides the class, the later ones only add to the summary.

1. Scaffold, in a source repository only (``sdk-*`` other than sdk-core, sdk-template and
   sdk-gates): the base has no ``src/`` directory.
2. Render trust: a changed file the template owns (rendered, and matched by no
   ``_skip_if_exists`` pattern) whose content and executable bit are identical to the
   template rendered at the head's ``_commit`` with the head's answers leaves the changed
   set. The render runs at
   the SHA ``_commit`` resolves to on the template's main. A render that fails trusts
   nothing. A change to ``.copier-answers.yml`` other than ``_commit`` moving forward
   along the template's main, ``core_version`` or ``core_git_ref`` is the session's:
   ``human``; an answer the base lacks (a question a template release added) is free
   when it equals the question's literal default at the head's ``_commit``. The answers
   file is read only inside a subset of YAML (``answers_problems``), and when it changed
   or anything is trusted it must be byte-identical to the one copier writes back in the
   render. A non-empty ``core_git_ref`` on the head must be ``main`` or a full SHA (40
   lowercase hex characters, which uv takes as the commit itself) of a commit on
   sdk-core's main.
3. Protected paths in what remains; everywhere, also the build and install tables of
   ``pyproject.toml``; in a source, also a template-owned file under ``src/`` that
   differs from the render (an adapter changed by hand) and a template-owned test file
   (``tests/test_family.py``, ``tests/conftest.py``) that differs from the render or is
   deleted (the family check or its plugin line turned off); in sdk-template, the template
   origin of every path protected in a source, any path under ``template/`` with Jinja in
   its name, the dependency, build and install tables of ``template/pyproject.toml.jinja``
   (read past Jinja, comments and strings, keys as TOML spells them, a key or header with
   a backslash refused; one that ends inside a multi-line string is human), any changed
   line of it that carries Jinja, and any changed line of it that looks like one of those
   tables or their keys; in ``xippios/sdk-gates`` every pull request.
4. First surface: a ``src/xippios/**/tasks.py`` whose ``__all__`` was empty or absent
   names at least one task. Bootstrap: in a source whose base exports no task, any
   changed file under ``src/``.
5. Release: the ``[project]`` version of ``pyproject.toml`` changed, and what remains is
   not a subset of the release files.
6. Otherwise ``auto``.

"Base" for rule 1 is the base commit itself; every comparison of content (the changed set,
rules 2 to 5) is against the merge base of base and head, which is the base itself once a
pull request is up to date with its branch. The branch name is no input.

Standard library only, so a workflow runs it with the runner's ``python3``; the render
calls ``uvx copier``, the core pin check clones sdk-core. Nothing from the pull request is
executed: its files are read as git objects, and git clone, uv and copier run in a
temporary directory outside the checkout.

Exit status: 0 for ``auto``, 1 for ``human``, 2 when the classification itself failed.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

AUTO = "auto"
HUMAN = "human"

DEFAULT_TEMPLATE_URL = "https://github.com/xippios/sdk-template.git"
DEFAULT_CORE_URL = "https://github.com/xippios/sdk-core.git"
# A core_git_ref other than empty is this branch of sdk-core, or a full SHA on it.
CORE_BRANCH = "main"
CORE_PIN = "core_git_ref"
# uv takes a rev of 40 hex characters as the commit itself, never as a branch or a tag.
FULL_SHA = re.compile(r"[0-9a-f]{40}")
CORE_OFF_MAIN = "core pinned off main or not a full SHA"
# The template's _commit is trusted only when it is on this branch of the template.
TEMPLATE_BRANCH = "main"
COPIER_SPEC = "copier>=9,<10"
# Seconds, for the template clone and for the render each: both end well inside the
# workflow job's 20 minutes, so a hung one still yields a classification and its reasons.
RENDER_TIMEOUT = 300
ANSWERS_FILE = ".copier-answers.yml"
# The answers a pull request changes without a human: _commit moving forward along the
# template's main (checked against the template), and the core pins.
FREE_ANSWERS = frozenset({"_commit", "core_version", "core_git_ref"})
# Read by the classifier as one-line scalars: no continuation line may follow them.
SINGLE_LINE_ANSWERS = ("_commit", "core_version", "core_git_ref")
NOT_CANONICAL = (
    "answers file is not in copier's canonical form: it differs from the "
    f"{ANSWERS_FILE} the render writes back; nothing is trusted"
)
NOT_CHECKED_CANONICAL = (
    f"answers file changed and is not checked against copier's canonical form: no render "
    f"wrote {ANSWERS_FILE} back"
)

PROTECTED = (
    ".github/**",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/agents/**",
    ".claude/hooks/**",
    ".claude/commands/**",
    ".mcp.json",
    "CLAUDE.local.md",
    ".pre-commit-config.yaml",
    ".secrets.baseline",
    # hatchling merges a root hatch.toml over [tool.hatch], a build route (BUILD_NAMES).
    "hatch.toml",
    # uv reads a root uv.toml as it reads [tool.uv], and in its place when both exist.
    "uv.toml",
    "docs/conventions.md",
    "docs/adr/**",
    "docs/review-checklist.md",
    "docs/definition-of-done.md",
)
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
        *template_origins(PROTECTED),
    ),
}
# In sdk-template, protected when its dependency block changes.
TEMPLATE_PYPROJECT = "template/pyproject.toml.jinja"
# Template-owned modules under src/ by name, for when no render tells which files the
# template owns (--no-render, a failed render).
ADAPTER_MODULES = re.compile(r"src/xippios/(?:.+/)?(?:mcp|http|_version|api/__init__)\.py")
# The template-owned test files that carry the family conformance check and the plugin
# line that serves it; template-owned by name, too, when no render tells. tests/test_tasks.py
# is the session's (skip-listed).
FAMILY_TEST_FILES = frozenset({"tests/test_family.py", "tests/conftest.py"})
# The gates repository itself, this classifier's home: every pull request there is human.
ORG_REPOSITORY = "sdk-gates"
# The repositories named sdk-* that are not sources: rule 1, the source checks of rule 3 and
# the bootstrap of rule 4 skip them. The gates repository's name matches sdk-* since its
# rename from .github, so it is listed here and never counts as a source.
FAMILY_REPOSITORIES = frozenset({"sdk-core", "sdk-template", ORG_REPOSITORY})

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
    """A clone, the render or the template's settings failed: nothing trusted or checked."""


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
    ).stdout.decode("utf-8", errors="surrogateescape")
    return sorted(p for p in out.split("\0") if p)


def plain_path(path: str) -> bool:
    """Whether ``path`` is relative, with no empty, ``.`` or ``..`` component."""
    return not path.startswith("/") and all(part not in {"", ".", ".."} for part in path.split("/"))


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


def list_files(workdir: Path, rev: str, path: str) -> list[str]:
    """Every file path under the directory ``path`` at ``rev``."""
    out = _git(workdir, "ls-tree", "-r", "-z", "--name-only", "--full-tree", rev, "--", path)
    return [p for p in out.stdout.decode("utf-8", errors="surrogateescape").split("\0") if p]


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


# A top-level line inside the reader's subset: an unquoted plain key, a colon, then a
# blank or the end of the line (YAML reads `key:value` as one scalar, not as a key).
_PLAIN_KEY_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t].*)?")


def answers_problems(source: bytes | None) -> list[str]:
    """Why an answers file lies outside the subset of YAML this reader reads; [] inside.

    The subset: UTF-8; every line at column 0 blank, a ``#`` comment or a ``key: value``
    line with an unquoted plain key; no top-level key twice; no continuation line under
    ``_commit``, ``core_version`` or ``core_git_ref``. Outside it YAML may load a key or a
    value this reader does not see (a quoted key, the later of two duplicates, a scalar
    that goes on), so the file is ``human`` and nothing is trusted.
    """
    if source is None:
        return []
    try:
        text = source.decode()
    except UnicodeDecodeError:
        return [f"{ANSWERS_FILE} is not UTF-8"]
    seen: set[str] = set()
    repeated: list[str] = []
    odd: list[str] = []
    continued: list[str] = []
    key: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        if line[0] in " \t":
            if key in SINGLE_LINE_ANSWERS and key not in continued:
                continued.append(key)
            continue
        match = _PLAIN_KEY_LINE.fullmatch(line)
        if match is None:
            odd.append(str(number))
            key = None
            continue
        key = match.group(1)
        if key in seen and key not in repeated:
            repeated.append(key)
        seen.add(key)
    problems: list[str] = []
    if repeated:
        keys = "key" if len(repeated) == 1 else "keys"
        problems.append(f"{ANSWERS_FILE} repeats the top-level {keys} {', '.join(repeated)}")
    if odd:
        lines = "line" if len(odd) == 1 else "lines"
        problems.append(
            f"{ANSWERS_FILE} {lines} {', '.join(odd)}: neither blank, a comment nor a "
            "key: value line with a plain key"
        )
    if continued:
        problems.append(f"{ANSWERS_FILE} continues {', '.join(continued)} on another line")
    return problems


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


_QUOTED = re.compile(r"""(?:'((?:[^']|'')*)'|"([^"\\]*)")\s*(?:#.*)?""")
# Jinja that copier renders in a default: a value carrying it is no literal.
_JINJA = ("{{", "{%", "{#")
# A plain scalar YAML may load as something other than a string: null, a boolean (YAML 1.1
# words included), a number or a date.
_TYPED = re.compile(r"~|null|true|false|yes|no|on|off|y|n|[-+]?\.?\d.*|[-+]?\.(?:inf|nan)", re.I)


@dataclass(frozen=True)
class Scalar:
    """A one-line YAML scalar: its text, and whether it was quoted."""

    text: str
    quoted: bool

    def same(self, other: Scalar) -> bool:
        """Whether both load as the same value (``1`` is no ``'1'``, ``abc`` is ``"abc"``).

        Equal text, and equal quoting unless the plain one can only be a string.
        """
        if self.text != other.text:
            return False
        return self.quoted == other.quoted or not _TYPED.fullmatch(self.text)


def literal_scalar(value: str) -> Scalar | None:
    """The scalar a one-line YAML value spells when it is a literal, else None.

    A literal is a plain scalar or a quoted one without escapes, a trailing comment
    allowed, and no Jinja: not empty (null), not a block scalar, a flow collection, an
    anchor, an alias or a tag.
    """
    text = value.strip()
    if not text or text[0] in "|>[{&*!#":
        return None
    if text[0] in "'\"":
        match = _QUOTED.fullmatch(text)
        if match is None:
            return None
        double = match.group(1) is None
        scalar = Scalar(match.group(2) if double else match.group(1).replace("''", "'"), True)
    else:
        scalar = Scalar(re.sub(r"\s+#.*$", "", text), False)
    return None if any(mark in scalar.text for mark in _JINJA) else scalar


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _mapping_default(body: Sequence[str]) -> Scalar | None:
    """The literal ``default`` of a question written as a block mapping, else None."""
    content = [line for line in body if line.strip() and not line.lstrip().startswith("#")]
    if not content or _indent(content[0]) == 0:
        return None
    level = _indent(content[0])
    found: list[Scalar | None] = []
    for i, line in enumerate(content):
        match = re.fullmatch(r"default\s*:(.*)", line.strip())
        if _indent(line) != level or match is None:
            continue
        continued = i + 1 < len(content) and _indent(content[i + 1]) > level
        found.append(None if continued else literal_scalar(match.group(1)))
    return found[0] if len(found) == 1 else None


def question_defaults(copier_yml: str) -> dict[str, Scalar | None]:
    """Each question of a copier.yml with its literal default; None when it has none.

    A question is a top-level key not starting with ``_``. Its default is the value of
    ``default`` in its mapping, or, in the short form ``name: value``, the value itself;
    it counts only as a literal (``literal_scalar``). A question defined twice has none.
    """
    defaults: dict[str, Scalar | None] = {}
    for key, lines in answer_entries(copier_yml):
        if key is None or key.startswith("_"):
            continue
        rest = lines[0].split(":", 1)[1].strip()
        if rest and not rest.startswith("#"):
            value = literal_scalar(rest)
        else:
            value = _mapping_default(lines[1:])
        defaults[key] = None if key in defaults else value
    return defaults


def _is_default(lines: Sequence[str], default: Scalar | None) -> bool:
    """Whether an answer's lines are one literal equal to its question's literal default."""
    if default is None or len(lines) != 1:
        return False
    value = lines[0].split(":", 1)[1]
    # YAML reads `key:value` as one plain scalar, not as a key and its value.
    answer = literal_scalar(value) if value[:1].isspace() else None
    return answer is not None and answer.same(default)


def answer_changes(
    before: bytes | None,
    after: bytes | None,
    forward: bool | None,
    defaults: Mapping[str, Scalar | None] | None = None,
) -> list[str]:
    """Rule 2's human reasons for a change to the answers file.

    ``forward`` says whether the head's ``_commit`` descends from the base's on the
    template's main: None when the template could not be checked (``--no-render``, a
    failed clone, a ``_commit`` the render refused), which leaves any change of it human.
    ``defaults`` are the template's questions at the head's ``_commit`` with their
    literal defaults (``question_defaults``), None when the template could not be read:
    an answer the base lacks is free when it equals its question's literal default, and
    human with another value, a default that is not literal, or a question unknown there.
    """
    old, new = answer_table(before), answer_table(after)
    keys = sorted(k for k in (old.keys() | new.keys()) - FREE_ANSWERS if old.get(k) != new.get(k))
    changed = [k for k in keys if k in old]
    added = [k for k in keys if k not in old]
    if defaults is not None:
        added = [k for k in added if not _is_default(new[k], defaults.get(k))]
    reasons = [f"answers changed: {', '.join(changed)}"] if changed else []
    if added and defaults is not None:
        reasons.append(f"answers added with non-default values: {', '.join(added)}")
    elif added:
        reasons.append(f"answers added, not checked against the template: {', '.join(added)}")
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


def _binds(node: ast.AST, name: str) -> bool:
    """Whether ``node`` binds or deletes ``name`` (an assignment, a def, an import, ...)."""
    match node:
        case ast.Name(id=found, ctx=ast.Store() | ast.Del()):
            return found == name
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return node.name == name
        case ast.alias():
            return (node.asname or node.name.split(".")[0]) == name
        case ast.ExceptHandler() | ast.MatchAs() | ast.MatchStar():
            return node.name == name
        case ast.MatchMapping():
            return node.rest == name
        case ast.Global() | ast.Nonlocal():
            return name in node.names
    return False


# Builtins that reach a module's namespace by name, so __all__ through a computed string.
_DYNAMIC_BUILTINS = frozenset(
    {"globals", "vars", "locals", "setattr", "delattr", "exec", "eval", "__import__"}
)


def _dynamic(tree: ast.Module) -> bool:
    """Whether a module may set ``__all__`` in a way no static reading follows.

    A ``"__all__"`` string (``globals()["__all__"]``, ``setattr(module, "__all__", ...)``),
    a builtin that reaches the namespace by name, ``sys.modules`` or a ``__dict__``, a
    star import, or a module ``__getattr__``, which answers for an absent ``__all__``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "__all__":
            return True
        if isinstance(node, ast.Name) and node.id in _DYNAMIC_BUILTINS:
            return True
        if isinstance(node, ast.Attribute) and (
            node.attr == "__dict__" or (node.attr == "modules" and isinstance(node.value, ast.Name))
        ):
            return True
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            return True
        if _binds(node, "__getattr__"):
            return True
    return False


def exported_names(source: bytes | None) -> list[str] | None:
    """The names in a module's literal ``__all__``.

    ``[]`` when the module or its ``__all__`` is absent; None when ``__all__`` cannot be
    read statically: anything but top-level assignments of a literal list or tuple of
    strings (and ``+=`` of one), any other mention of ``__all__`` (a call of one of its
    methods, a binding by import, def or loop, a read that could alias it), or a module
    that reaches its namespace dynamically (see ``_dynamic``).
    """
    if source is None:
        return []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if _dynamic(tree):
        return None
    names: list[str] = []
    literal_targets: set[int] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(_is_all(t) for t in targets):
            continue
        if not all(isinstance(t, ast.Name) for t in targets):
            return None
        literal_targets.update(id(t) for t in targets)
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
    for node in ast.walk(tree):
        mentions = _binds(node, "__all__") or _is_all(node)
        if mentions and id(node) not in literal_targets:
            return None
    return names


# A key as TOML spells it: basic strings (escapes included) and literal strings, whatever
# they hold, and any other character but a quote, ``=`` (for a key) or a bracket (for a
# header); so spaces and tabs around the dots and the name, and a blanked Jinja
# expression, belong to the key (``_toml_name`` strips them). A quote opens a string and
# never stands alone, and no whitespace is matched outside the name: each line has one
# reading, so a long line cannot make the match backtrack.
_STRING = r""""(?:[^"\\]|\\.)*"|'[^']*'"""
_KEY_NAME = rf"""(?:{_STRING}|[^"'=])+?"""
_HEADER_NAME = rf"""(?:{_STRING}|[^"'\[\]])+?"""
_TABLE = re.compile(rf"^\[({_HEADER_NAME})\]\s*(?:#.*)?$")
_ARRAY_TABLE = re.compile(rf"^\[\[({_HEADER_NAME})\]\]\s*(?:#.*)?$")
_KEY = re.compile(rf"^({_KEY_NAME})=(.*)$")
# The dependency lists of a pyproject: these tables and keys, and everything below them.
DEPENDENCY_NAMES = (
    "project.dependencies",
    "project.optional-dependencies",
    "dependency-groups",
)
# Where a package is built from and installed from, and the commands it installs: these
# tables and keys, and everything below them (tool.uv: index, sources, overrides, ...;
# tool.hatch: the packaged paths, targets and build hooks, the metadata hooks and the
# version source, which run code at build time; a root hatch.toml is a protected path).
BUILD_NAMES = (
    "build-system",
    "tool.uv",
    "tool.hatch",
    "project.scripts",
    "project.gui-scripts",
    "project.entry-points",
)


def _toml_name(text: str) -> str:
    """A dotted key or header name, its parts stripped of spaces, tabs and quotes.

    A dot inside a quoted part splits it too, which only adds parts: a protected name has
    no dot in its parts, so it reads the same. An escape is left as written (``_escaped``).
    """
    return ".".join(part.strip().strip("\"'") for part in text.split("."))


def _escaped(name: str) -> bool:
    """Whether a key or header carries a backslash: a basic-string escape can spell any name."""
    return "\\" in name


def _in_block(name: str, names: Iterable[str]) -> bool:
    """Whether ``name`` is one of ``names`` or below one; a name with an escape always is."""
    return _escaped(name) or any(name == top or name.startswith(top + ".") for top in names)


def _nesting(text: str) -> int:
    return text.count("[") + text.count("{") - text.count("]") - text.count("}")


_JINJA_CLOSE = {"{{": "}}", "{%": "%}", "{#": "#}"}


def _blank_jinja(text: str) -> tuple[str, bool]:
    """``text`` with every Jinja expression, tag and comment blanked, line breaks kept.

    Jinja reads the template before TOML does, inside TOML strings and comments too. The
    second value says whether one is still open at the end.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        close = _JINJA_CLOSE.get(text[i : i + 2])
        if close is None:
            out.append(text[i])
            i += 1
            continue
        end = text.find(close, i + 2)
        stop = len(text) if end == -1 else end + 2
        out.append(re.sub(r"[^\n]", " ", text[i:stop]))
        if end == -1:
            return "".join(out), True
        i = stop
    return "".join(out), False


@dataclass(frozen=True)
class TomlLine:
    """One line of a pyproject template as the dependency scan reads it."""

    raw: str
    # Jinja blanked and the comment cut, strings kept: where headers and keys are read.
    code: str
    # ``code`` without its strings: where brackets are counted.
    bare: str
    # The line starts inside a multi-line string.
    in_string: bool


def toml_lines(text: str) -> tuple[list[TomlLine], str | None]:
    """The lines of a pyproject template, with Jinja, comments and strings told apart.

    Jinja first, as copier renders it (``_blank_jinja``); then TOML: a ``#`` outside a
    string cuts the rest of its line, and basic and literal strings, one-line and
    multi-line (between three quotes), stay in ``code`` and leave ``bare``. The second
    value names what is still open at the end (a multi-line string, a Jinja tag), or None.
    """
    blanked, jinja_open = _blank_jinja(text)
    lines: list[TomlLine] = []
    quote: str | None = None  # the open string's delimiter: one quote or three
    for raw, line in zip(text.split("\n"), blanked.split("\n"), strict=True):
        in_string = quote is not None
        code: list[str] = []
        bare: list[str] = []
        i = 0
        while i < len(line):
            char = line[i]
            if quote is None:
                if char == "#":
                    break
                if char in "\"'":
                    quote = line[i : i + 3] if line.startswith(char * 3, i) else char
                    code.append(quote)
                    i += len(quote)
                    continue
                code.append(char)
                bare.append(char)
                i += 1
            elif char == "\\" and quote[0] == '"':  # an escape in a basic string
                code.append(line[i : i + 2])
                i += 2
            elif line.startswith(quote, i):
                # A multi-line string may end in up to two more quotes, which it contains.
                end = i + len(quote)
                while len(quote) == 3 and end < len(line) and line[end] == quote[0]:
                    end += 1
                code.append(line[i:end])
                i = end
                quote = None
            else:
                code.append(char)
                i += 1
        if quote in {'"', "'"}:
            quote = None  # a one-line string ends with its line
        lines.append(TomlLine(raw, "".join(code), "".join(bare), in_string))
    if quote is not None:
        return lines, "a multi-line string"
    return lines, "a Jinja tag" if jinja_open else None


def dependency_block(
    text: str | None, names: Iterable[str] = DEPENDENCY_NAMES + BUILD_NAMES
) -> list[str] | None:
    """The dependency, build and install tables of a pyproject template, as stripped lines.

    Read as text, since a Jinja template is not TOML: ``[project] dependencies``,
    ``[project.optional-dependencies]``, ``[dependency-groups]``, ``[build-system]``,
    ``[tool.uv]``, ``[tool.hatch]``, ``[project.scripts]``, ``[project.gui-scripts]`` and
    ``[project.entry-points.*]``, whether written as tables, as dotted keys or as multi-line
    values, Jinja lines included; each line with its table. Headers, keys and brackets are
    read past Jinja, comments and strings (``toml_lines``): a bracket in a comment or a
    string opens nothing, and a header inside a multi-line string is none. A header or key
    is read as TOML spells it (quoted parts with any content, spaces and tabs around the
    dots); one with a backslash belongs to the block whatever it names (``_in_block``).
    """
    if text is None:
        return None
    block: list[str] = []
    table = ""
    depth = 0
    keep = False
    for line in toml_lines(text)[0]:
        stripped = line.raw.strip()
        if depth > 0 or line.in_string:
            if keep:
                block.append(f"{table}: {stripped}")
            depth += _nesting(line.bare)
            continue
        code = line.code.strip()
        header = _TABLE.match(code) or _ARRAY_TABLE.match(code)
        if header:
            table = _toml_name(header.group(1))
            continue
        if _in_block(table, names):
            if stripped:
                block.append(f"{table}: {stripped}")
            depth = max(_nesting(line.bare), 0)
            keep = True
            continue
        key = _KEY.match(code)
        if key:
            name = _toml_name(f"{table}.{key.group(1)}" if table else key.group(1))
            keep = _in_block(name, names)
            if keep:
                block.append(f"{table}: {stripped}")
            depth = max(_nesting(line.bare), 0)
    return block


def _changed_lines(before: str | None, after: str | None) -> list[str]:
    """The lines a diff of two texts adds, removes, changes or moves, both sides."""
    old = before.splitlines() if before is not None else []
    new = after.splitlines() if after is not None else []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    changed: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            changed += [*old[i1:i2], *new[j1:j2]]
    return changed


def jinja_lines_changed(before: str | None, after: str | None) -> bool:
    """Whether a line that carries Jinja was added, removed, changed or moved."""
    return any(mark in line for line in _changed_lines(before, after) for mark in _JINJA)


# The second net over a pyproject template's changed lines: these tables, named by a line
# read on its own.
NET_NAMES = (
    "tool.uv",
    "build-system",
    "tool.hatch",
    "project.scripts",
    "project.gui-scripts",
    "project.entry-points",
    "dependency-groups",
    "project.optional-dependencies",
)
_HEADER_LIKE = re.compile(rf"\[\[?({_HEADER_NAME})\]")


def looks_protected(line: str, names: Iterable[str] = NET_NAMES) -> bool:
    """Whether a line, read on its own, could name one of ``names`` or a key below one.

    A table header (``[tool.uv]``, ``[[tool.uv.index]]``), or a key whose parts begin with
    a tail of a name (``tool.uv.index-url``, ``uv.index-url`` under ``[tool]``,
    ``scripts.x`` under ``[project]``, a bare ``uv``) or lead to one (``tool``, ``project``:
    an inline table can hold it). Without its context, in a string, an array or a comment
    the line counts all the same, and so does a header or key with a backslash in it.
    """
    text = line.strip()
    header = _HEADER_LIKE.match(text)
    if header:
        return _in_block(_toml_name(header.group(1)), names)
    key = _KEY.match(text)
    if key is None:
        return False
    if _escaped(key.group(1)):
        return True
    parts = _toml_name(key.group(1)).split(".")
    for name in names:
        target = name.split(".")
        if parts == target[: len(parts)]:
            return True
        if any(parts[: len(target) - i] == target[i:] for i in range(len(target))):
            return True
    return False


def protected_lines_changed(before: str | None, after: str | None) -> list[str]:
    """The changed lines (``_changed_lines``) that look protected (``looks_protected``)."""
    found: list[str] = []
    for line in _changed_lines(before, after):
        text = line.strip()
        if looks_protected(text) and text not in found:
            found.append(text)
    return found


def build_routes(source: bytes | None) -> dict[str, object]:
    """The build and install tables of a pyproject.toml (``BUILD_NAMES``) that it has.

    Raises ValueError (TOMLDecodeError, UnicodeDecodeError) when it cannot be read.
    """
    if source is None:
        return {}
    data: object = tomllib.loads(source.decode())
    routes: dict[str, object] = {}
    for name in BUILD_NAMES:
        node = data
        for part in name.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            routes[name] = node
    return routes


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


def _clone(url: str, clone: Path, *options: str) -> Path:
    """Clone ``url`` into ``clone``, outside any checkout; RenderError when it fails."""
    try:
        proc = subprocess.run(
            ["git", "clone", "--quiet", *options, "--", url, str(clone)],
            cwd=clone.parent,
            capture_output=True,
            check=False,
            env=_env(),
            timeout=RENDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"cloning {url} timed out") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise RenderError(f"cannot clone {url}: {detail}")
    return clone


def _clone_template(template_url: str, scratch: Path) -> Path:
    """A bare-bones clone of the template (no checkout), with its tags and its main."""
    return _clone(template_url, scratch / "template", "--no-checkout")


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


def _copier_yml(clone: Path, sha: str) -> str:
    """The template's copier.yml at ``sha``."""
    for name in ("copier.yml", "copier.yaml"):
        content = read_blob(clone, sha, name)
        if content is not None:
            return content.decode()
    raise RenderError(f"the template has no copier.yml at {sha}")


OUTSIDE_SUBSET = f"{ANSWERS_FILE} lies outside the subset the classifier reads; nothing is trusted"

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
    # The template's questions at the head's _commit with their literal defaults; None
    # when its copier.yml could not be read there.
    defaults: dict[str, Scalar | None] | None = None
    # Whether the head's answers file is byte-identical to the one the render writes back;
    # None when no render ran.
    canonical: bool | None = None
    # Rule 2's human reasons from the render (the answers file not in canonical form).
    problems: list[str] = field(default_factory=list)


def _moves_forward(clone: Path, old: str, new_sha: str) -> bool:
    """Whether the template commit ``old`` is an ancestor of ``new_sha``."""
    if not _GIT_REF.fullmatch(old):
        return False
    try:
        old_sha = resolve(clone, old)
    except ClassifyError:
        return False
    return _git(clone, "merge-base", "--is-ancestor", old_sha, new_sha, check=False).returncode == 0


def core_ref_on_main(core_url: str, ref: str) -> bool:
    """Whether ``ref`` pins sdk-core to its main or to a full SHA of a commit on its main.

    ``main`` is accepted unread: uv takes a rev as a branch before a tag or a commit. A full
    SHA, 40 lowercase hex characters, uv takes as the commit itself, so no branch or tag
    named like it can take it over; it must name a commit on main, read from a clone
    without trees and blobs, which holds every commit on main. Every other form (a ``v*``
    tag, a short hex, another branch, ``refs/...``) is refused unread, since a branch
    created later by its name would take it over at the next ``uv lock``. RenderError when
    the clone fails.
    """
    if ref == CORE_BRANCH:
        return True
    if not FULL_SHA.fullmatch(ref):
        return False
    with tempfile.TemporaryDirectory(prefix="merge-class-core-") as tmp:
        clone = _clone(core_url, Path(tmp) / "sdk-core", "--bare", "--filter=tree:0")
        # git, like uv, reads 40 hex characters as the object, whatever ref bears the name.
        kind = _git(clone, "cat-file", "-t", ref, check=False)
        if kind.returncode != 0 or kind.stdout.strip() != b"commit":
            return False
        main = f"refs/heads/{CORE_BRANCH}"
        return _git(clone, "merge-base", "--is-ancestor", ref, main, check=False).returncode == 0


def core_pin_reason(
    before: bytes | None, after: bytes | None, render: bool, core_url: str
) -> str | None:
    """Rule 2's human reason against the head's ``core_git_ref``, or None.

    A non-empty ``core_git_ref`` on the head must be ``main`` or a full SHA of a commit on
    sdk-core's main (``core_ref_on_main``), whether or not the pull request changes it:
    while core is pinned off main or by another form, every pull request is human. A full
    SHA that cannot be checked (a failed clone) is human too; under ``--no-render`` a
    change to a non-empty value is. Empty or absent, there is no pin. An answers file
    outside the reader's subset (``answers_problems``) is human: YAML may read a pin this
    reader does not see.
    """
    if answers_problems(after):
        return f"{CORE_PIN} not read: {ANSWERS_FILE} lies outside the subset the classifier reads"
    old, new = answer_table(before), answer_table(after)
    if CORE_PIN not in new:
        return None
    ref = answer_scalar(answer_entries(_text(after or b"")), CORE_PIN)
    if ref == "":
        return None
    if ref is None:
        return f"{CORE_OFF_MAIN}: {CORE_PIN} is no plain scalar"
    if not render:
        changed = old.get(CORE_PIN) != new.get(CORE_PIN)
        return f"{CORE_PIN} changes to {ref}, not checked against sdk-core" if changed else None
    try:
        on_main = core_ref_on_main(core_url, ref)
    except RenderError as exc:
        return f"{CORE_PIN} {ref} not checked against sdk-core: {exc}"
    if on_main:
        return None
    return (
        f"{CORE_OFF_MAIN}: {CORE_PIN} {ref} is neither sdk-core's main nor the full SHA of a "
        "commit on its main"
    )


def trust_rendered(
    workdir: Path,
    head: str,
    changed: Sequence[str],
    template_url: str,
    renderer: Renderer,
    base_commit: str | None = None,
) -> Trust:
    """Rule 2: the changed template-owned files identical to the render, mode included.

    ``base_commit`` is the base's ``_commit``; when the head's differs, the template clone
    also tells whether it moved forward. An answers file outside the reader's subset
    (``answers_problems``) trusts nothing; one that changed, or that anything is trusted
    with, must be byte-identical to the one copier writes back in the render, else nothing
    is trusted and the reason is ``NOT_CANONICAL``.
    """
    answers = read_blob(workdir, head, ANSWERS_FILE)
    if answers is None:
        return Trust([], None, f"no {ANSWERS_FILE} on the head; nothing is trusted")
    if answers_problems(answers):
        return Trust([], None, OUTSIDE_SUBSET)
    entries = answer_entries(answers.decode())
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
        defaults: dict[str, Scalar | None] | None = None
        try:
            clone = _clone_template(template_url, scratch)
            sha = _on_main(clone, commit)
            if base_commit is not None and base_commit != commit:
                forward = _moves_forward(clone, base_commit, sha)
            copier_yml = _copier_yml(clone, sha)
            defaults = question_defaults(copier_yml)
            raw_patterns = skip_patterns(copier_yml)
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
            return Trust([], commit, note, commit_forward=forward, defaults=defaults)
        trusted: list[str] = []
        owned: list[str] = []
        root = dest.resolve()
        for path in changed:
            if not plain_path(path) or matches_any(path, patterns):
                continue  # no file of the render, or filled by the session; never trusted
            rendered = dest / path
            if (
                rendered.is_symlink()
                or not rendered.is_file()
                or not rendered.resolve().is_relative_to(root)
            ):
                continue  # the template does not render it
            owned.append(path)
            entry = tree_entry(workdir, head, path)
            if entry is None or entry[1] != "blob" or entry[0] not in REGULAR_FILE_MODES:
                continue  # deleted, a symlink or a submodule on the head
            # The executable bit is part of the file: a mode-only difference is no match.
            mode = "100755" if rendered.stat().st_mode & stat.S_IXUSR else "100644"
            ours = _git(workdir, "cat-file", "blob", entry[2]).stdout
            if entry[0] == mode and rendered.read_bytes() == ours:
                trusted.append(path)
        # The answers as copier writes them back, _commit and _src_path included: a form
        # YAML reads otherwise than this reader (a quoted key, a duplicate) cannot match.
        written = dest / ANSWERS_FILE
        canonical = (
            not written.is_symlink() and written.is_file() and written.read_bytes() == answers
        )
    if not canonical and (ANSWERS_FILE in changed or trusted):
        return Trust([], commit, None, sha, forward, owned, defaults, False, [NOT_CANONICAL])
    return Trust(trusted, commit, None, sha, forward, owned, defaults, canonical)


# --- classification ----------------------------------------------------------------------


def _repo_name(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1]


def is_source(name: str) -> bool:
    """Whether a repository is a source: named ``sdk-*`` and none of FAMILY_REPOSITORIES.

    sdk-core, sdk-template and the gates repository (``ORG_REPOSITORY``, named ``sdk-*``
    since its rename from .github) are no sources.
    """
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
    core_url: str = DEFAULT_CORE_URL,
) -> Classification:
    """Classify the pull request from ``base`` to ``head`` of ``repo`` in ``workdir``."""
    base_sha = resolve(workdir, base)
    head_sha = resolve(workdir, head)
    fork = merge_base(workdir, base_sha, head_sha)
    changed = changed_files(workdir, fork, head_sha)
    result = Classification(repo, base_sha, head_sha, fork, changed)
    name = _repo_name(repo)
    add = result.findings.append

    # 1. Scaffold, sources only, settled by name before rule 1: sdk-core, sdk-template and
    # the gates repository (ORG_REPOSITORY, named sdk-* too) are no sources.
    source = is_source(name)
    if source:
        entry = tree_entry(workdir, base_sha, "src")
        if entry is None or entry[1] != "tree":
            add(Finding(1, "scaffold: the base has no src/ directory"))

    # 2. Render trust, and the answers file. git never writes a path that is not plain; a
    # tree crafted to carry one is never trusted.
    for path in changed:
        if not plain_path(path):
            add(Finding(2, f"{path} is no plain relative path; never trusted"))
    before_answers = read_blob(workdir, fork, ANSWERS_FILE)
    after_answers = read_blob(workdir, head_sha, ANSWERS_FILE)
    # The head's answers, whether or not the pull request changes them: outside the
    # reader's subset nothing is trusted and nothing read from them counts.
    subset = answers_problems(after_answers)
    for problem in subset:
        add(Finding(2, problem))
    if subset:
        trust = Trust([], None, OUTSIDE_SUBSET)
    elif render:
        base_commit = answers_commit(before_answers)
        trust = trust_rendered(workdir, head_sha, changed, template_url, renderer, base_commit)
    else:
        trust = Trust([], None, "render skipped (--no-render); nothing is trusted")
    result.trusted = trust.trusted
    result.template_ref = trust.template_ref
    result.template_sha = trust.template_sha
    if trust.note:
        add(Finding(2, trust.note, human=False))
    for problem in trust.problems:
        add(Finding(2, problem))
    # Over the changed set, not what remains: the render writes the answers back as they are.
    if ANSWERS_FILE in changed:
        forward, defaults = trust.commit_forward, trust.defaults
        for reason in answer_changes(before_answers, after_answers, forward, defaults):
            add(Finding(2, reason))
        if trust.canonical is None and not subset:
            add(Finding(2, NOT_CHECKED_CANONICAL))
    # On every pull request: a pin off main keeps each one human until it is lifted.
    pin = core_pin_reason(before_answers, after_answers, render, core_url)
    if pin is not None:
        add(Finding(2, pin))
    remaining = [p for p in changed if p not in set(trust.trusted)]
    result.remaining = remaining

    # 3. Protected paths
    if name == ORG_REPOSITORY:
        add(Finding(3, f"every pull request of {repo} is human"))
    protected = PROTECTED + PROTECTED_BY_REPO.get(name, ())
    for path in remaining:
        hits = [p for p in protected if is_protected(path, p)]
        if hits:
            add(Finding(3, f"protected path {path} (matches {hits[0]})"))
            continue
        # An adapter changed by hand could expose tasks around rule 4.
        if source and path.startswith("src/"):
            if trust.owned is not None and path in trust.owned:
                add(Finding(3, f"{path} is template-owned and differs from the render"))
            elif trust.owned is None and ADAPTER_MODULES.fullmatch(path):
                add(Finding(3, f"{path} is template-owned and no render could compare it"))
        # The family check changed or deleted by hand would turn off silently. A deletion is
        # never identical to the render: human whatever the render says.
        if source and path in FAMILY_TEST_FILES:
            test_file = f"{path} is a template-owned test file"
            if tree_entry(workdir, head_sha, path) is None:
                add(Finding(3, f"{test_file} deleted by the pull request"))
            elif trust.owned is None:
                add(Finding(3, f"{test_file} and no render could compare it"))
            elif path in trust.owned:
                add(Finding(3, f"{test_file} changed by hand: not trusted as the render's"))
        # Jinja in a name can render to any path, a protected one included.
        jinja = "{{" in path or "{%" in path
        if name == "sdk-template" and path.startswith(TEMPLATE_DIR) and jinja:
            add(Finding(3, f"{path} carries Jinja in its name under {TEMPLATE_DIR}"))
    if name == "sdk-template" and TEMPLATE_PYPROJECT in remaining:
        before = read_blob(workdir, fork, TEMPLATE_PYPROJECT)
        after = read_blob(workdir, head_sha, TEMPLATE_PYPROJECT)
        old_text = before.decode() if before is not None else None
        new_text = after.decode() if after is not None else None
        still_open = toml_lines(new_text)[1] if new_text is not None else None
        if still_open:
            add(Finding(3, f"{TEMPLATE_PYPROJECT} ends inside {still_open}"))
        if dependency_block(old_text) != dependency_block(new_text):
            add(Finding(3, f"the dependency block of {TEMPLATE_PYPROJECT} changed"))
        if jinja_lines_changed(old_text, new_text):
            add(Finding(3, f"a line that carries Jinja changed in {TEMPLATE_PYPROJECT}"))
        # A second net, should the scan above misread the file: the changed lines alone.
        looks = protected_lines_changed(old_text, new_text)
        if looks:
            add(
                Finding(
                    3,
                    f"a changed line of {TEMPLATE_PYPROJECT} looks like a dependency, build or "
                    f"install table: {'; '.join(looks)}",
                )
            )
    # In every repository: where the package is built and installed from, and what it
    # installs. The dependency lists stay free.
    if "pyproject.toml" in remaining:
        try:
            old_routes = build_routes(read_blob(workdir, fork, "pyproject.toml"))
            new_routes = build_routes(read_blob(workdir, head_sha, "pyproject.toml"))
        except ValueError as exc:  # TOMLDecodeError and UnicodeDecodeError
            add(Finding(3, f"cannot read the build and install tables of pyproject.toml: {exc}"))
        else:
            tables = [n for n in BUILD_NAMES if old_routes.get(n) != new_routes.get(n)]
            if tables:
                routes = ", ".join(tables)
                add(Finding(3, f"build or install routes changed in pyproject.toml: {routes}"))

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
    # The static reading has limits (an adapter, a module the tasks import, a name bound at
    # run time): while the base exports no task, any change under src/ is human.
    if source:
        base_tasks = [p for p in list_files(workdir, fork, "src") if TASKS_MODULE.fullmatch(p)]
        exported = any(exported_names(read_blob(workdir, fork, p)) for p in base_tasks)
        bootstrap = [p for p in remaining if p.startswith("src/")]
        if not exported and bootstrap:
            add(
                Finding(
                    4,
                    "bootstrap: no tasks.py on the base exports a task, and src/ changes: "
                    + ", ".join(bootstrap),
                )
            )

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


def printable(text: str) -> str:
    """``text`` on one line: backticks and non-printable characters as escapes.

    File names and answers come from the pull request; escaped, a name cannot break out of
    its code span or its line in the summary, nor forge a line of the report.
    """
    out: list[str] = []
    for char in text:
        if char != "`" and char.isprintable():
            out.append(char)
            continue
        code = ord(char)
        if code < 0x100:
            out.append(f"\\x{code:02x}")
        elif code < 0x10000:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    return "".join(out)


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
            lines.append(f"- rule {finding.rule} ({name}, {effect}): {printable(finding.text)}")
    if not any(f.human for f in result.findings):
        lines.append("- rule 6: no rule says human, so `auto`")
    ref = f" at `{printable(result.template_ref)}`" if result.template_ref else ""
    if result.template_sha:
        ref += f" (`{result.template_sha[:12]}`)"
    lines += ["", f"### Trusted: byte-identical to the template{ref} ({len(result.trusted)})", ""]
    lines += [f"- `{printable(p)}`" for p in result.trusted] or ["- none"]
    lines += ["", f"### Remaining changed files ({len(result.remaining)})", ""]
    lines += [f"- `{printable(p)}`" for p in result.remaining] or ["- none"]
    return "\n".join(lines) + "\n"


def report_text(result: Classification) -> str:
    """The plain-text report printed to stdout."""
    lines = [f"class={result.merge_class}"]
    for finding in result.findings:
        effect = "human" if finding.human else "note"
        lines.append(f"rule {finding.rule} ({effect}): {printable(finding.text)}")
    ref = f" at {printable(result.template_ref)}" if result.template_ref else ""
    if result.template_sha:
        ref += f" ({result.template_sha[:12]})"
    trusted = ", ".join(map(printable, result.trusted)) or "-"
    remaining = ", ".join(map(printable, result.remaining)) or "-"
    lines.append(f"trusted{ref} ({len(result.trusted)}): {trusted}")
    lines.append(f"remaining ({len(result.remaining)}): {remaining}")
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
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL, help="sdk-core's git URL")
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
            core_url=args.core_url,
        )
    except (ClassifyError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        detail = printable(str(exc))
        print(f"class={HUMAN}\nmerge-class failed: {detail}", file=sys.stderr)
        _append(output, f"class={HUMAN}\n")
        _append(args.summary, f"## merge-class: classification failed\n\n{detail}\n")
        return 2
    print(report_text(result))
    _append(output, f"class={result.merge_class}\n")
    _append(args.summary, summary_markdown(result))
    return 1 if result.merge_class == HUMAN else 0


if __name__ == "__main__":
    sys.exit(main())
