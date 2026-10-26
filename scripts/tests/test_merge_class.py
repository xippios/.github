"""Tests for merge_class.py, offline: real temporary git repositories, a fake renderer.

One test per rule and per acceptance line of the merge-gate design the classifier can
prove on its own (the rulesets and identities it cannot).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import merge_class as mc
import pytest

SOURCE = "xippios/sdk-usda-psd"

COPIER_YML = """\
source_slug:
  type: str

_subdirectory: template
# Files a session fills: never overwritten by copier update.
_skip_if_exists:
  - src/xippios/{{ package_dir }}/__init__.py
  - src/xippios/{{ package_dir }}/_client.py
  - src/xippios/{{ package_dir }}/tasks.py
  - src/xippios/{{ package_dir }}/reference/**
  - scripts/**
  - tests/test_tasks.py
  - README.md
  - "CHANGELOG.md"
_message_after_copy: done
"""

PYPROJECT = """\
[project]
name = "xippios-usda-psd"
version = "{version}"
dependencies = ["xippios-core~=0.2.0"]
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    """Write (or, for None, delete) the files and commit; return the commit's SHA."""
    for path, content in files.items():
        target = repo / path
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@dataclass
class PR:
    workdir: Path
    base: str
    head: str


def make_pr(
    root: Path, base_files: dict[str, str | None], head_changes: dict[str, str | None]
) -> PR:
    """A repository whose main is the base and whose branch `feature` is the head."""
    repo = root / "pr"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    base = commit(repo, base_files, "base")
    git(repo, "checkout", "-q", "-b", "feature")
    head = commit(repo, head_changes, "head")
    return PR(repo, base, head)


@pytest.fixture
def template(tmp_path: Path) -> Path:
    """A template repository: v0.1.0 and v0.2.0 on main, `rogue-tag` on another branch."""
    repo = tmp_path / "sdk-template"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"copier.yml": COPIER_YML}, "v0.1.0")
    git(repo, "tag", "v0.1.0")
    commit(repo, {"CHANGELOG.md": "0.2.0\n"}, "v0.2.0")
    git(repo, "tag", "v0.2.0")
    git(repo, "checkout", "-q", "-b", "rogue")
    commit(repo, {"copier.yml": "_skip_if_exists: []\n"}, "never merged")
    git(repo, "tag", "rogue-tag")
    git(repo, "checkout", "-q", "main")
    return repo


def answers(src_path: Path | str, ref: str = "v0.2.0") -> str:
    return (
        "# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY\n"
        f"_commit: {ref}\n"
        f"_src_path: {src_path}\n"
        "api_key_env: ''\n"
        "import_path: usda.psd\n"
        "source_slug: usda-psd\n"
    )


def source_base(template: Path) -> dict[str, str | None]:
    """A source on template v0.1.0."""
    return {
        ".copier-answers.yml": answers(template, "v0.1.0"),
        ".github/workflows/ci.yml": "ci v1\n",
        ".github/workflows/live.yml": "live v1\n",
        ".pre-commit-config.yaml": "hooks v1\n",
        "pyproject.toml": PYPROJECT.format(version="0.2.0"),
        "README.md": "readme\n",
        "CHANGELOG.md": "changelog\n",
        "CLAUDE.md": "claude\n",
        "uv.lock": "lock v1\n",
        "src/xippios/usda/psd/__init__.py": "",
        "src/xippios/usda/psd/_client.py": "client\n",
        "src/xippios/usda/psd/mcp.py": "mcp v1\n",
        "src/xippios/usda/psd/tasks.py": '__all__ = ["get_data"]\n',
        "src/xippios/usda/psd/reference/README.md": "reference\n",
        "tests/conftest.py": "conftest v1\n",
    }


def rendered(template: Path) -> dict[str, str]:
    """What template v0.2.0 renders for this source (only the files the tests need)."""
    return {
        ".copier-answers.yml": answers(template),
        ".github/workflows/ci.yml": "ci v2\n",
        ".github/workflows/live.yml": "live v2\n",
        ".pre-commit-config.yaml": "hooks v2\n",
        "pyproject.toml": PYPROJECT.format(version="0.1.0"),
        "README.md": "readme stub\n",
        "src/xippios/usda/psd/_client.py": "client stub\n",
        "src/xippios/usda/psd/mcp.py": "mcp v2\n",
        "src/xippios/usda/psd/tasks.py": "__all__: list[str] = []\n",
        "src/xippios/usda/psd/reference/README.md": "reference stub\n",
        "tests/conftest.py": "conftest v2\n",
    }


class FakeRender:
    """Stands in for copier: writes fixed files, or fails like a render that cannot run."""

    def __init__(self, files: dict[str, str], error: str | None = None) -> None:
        self.files = files
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, template_url: str, vcs_ref: str, data_file: Path, dest: Path) -> None:
        self.calls.append((template_url, vcs_ref, data_file.read_text()))
        if self.error:
            raise mc.RenderError(self.error)
        for path, content in self.files.items():
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


def classify(
    pr: PR,
    *,
    repo: str = SOURCE,
    render: FakeRender | None = None,
    template: Path | None = None,
) -> mc.Classification:
    if render is None:
        return mc.classify(repo=repo, base=pr.base, head=pr.head, workdir=pr.workdir, render=False)
    return mc.classify(
        repo=repo,
        base=pr.base,
        head=pr.head,
        workdir=pr.workdir,
        template_url=str(template),
        renderer=render,
    )


def human_rules(result: mc.Classification) -> set[int]:
    return {f.rule for f in result.findings if f.human}


def notes(result: mc.Classification) -> list[str]:
    return [f.text for f in result.findings if not f.human]


# --- rule 1 ------------------------------------------------------------------------------


def test_scaffold_pr_is_human(tmp_path: Path) -> None:
    pr = make_pr(
        tmp_path,
        {"README.md": "stub\n"},
        {"src/xippios/usda/psd/__init__.py": "", "pyproject.toml": "[project]\n"},
    )
    result = classify(pr)
    assert result.merge_class == mc.HUMAN
    assert human_rules(result) == {1}


def test_ordinary_source_pr_is_auto(tmp_path: Path, template: Path) -> None:
    pr = make_pr(
        tmp_path,
        source_base(template),
        {"src/xippios/usda/psd/_client.py": "client, fixed\n", "tests/test_client.py": "ok\n"},
    )
    result = classify(pr)
    assert result.merge_class == mc.AUTO
    assert human_rules(result) == set()


# --- rule 2 ------------------------------------------------------------------------------


def test_template_owned_file_identical_to_the_render_is_trusted(
    tmp_path: Path, template: Path
) -> None:
    pr = make_pr(
        tmp_path,
        source_base(template),
        {"tests/conftest.py": "conftest v2\n", "src/xippios/usda/psd/mcp.py": "mcp, edited\n"},
    )
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.trusted == ["tests/conftest.py"]
    assert result.remaining == ["src/xippios/usda/psd/mcp.py"]
    assert result.template_ref == "v0.1.0"  # the head's _commit


def test_skip_listed_file_is_never_trusted(tmp_path: Path, template: Path) -> None:
    pr = make_pr(
        tmp_path,
        source_base(template),
        {
            "README.md": "readme stub\n",
            "src/xippios/usda/psd/_client.py": "client stub\n",
            "src/xippios/usda/psd/tasks.py": "__all__: list[str] = []\n",
            "src/xippios/usda/psd/reference/README.md": "reference stub\n",
        },
    )
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.trusted == []
    assert len(result.remaining) == 4


def test_file_the_template_does_not_render_is_never_trusted(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), {"scripts/check-siblings.sh": "#!/bin/sh\n"})
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.trusted == []


def test_deleted_template_file_is_not_trusted(tmp_path: Path, template: Path) -> None:
    files = rendered(template)
    del files[".github/workflows/live.yml"]
    pr = make_pr(tmp_path, source_base(template), {".github/workflows/live.yml": None})
    result = classify(pr, render=FakeRender(files), template=template)
    assert result.trusted == []
    assert result.merge_class == mc.HUMAN


def test_render_gets_the_answers_without_commit_and_src_path(
    tmp_path: Path, template: Path
) -> None:
    render = FakeRender(rendered(template))
    pr = make_pr(tmp_path, source_base(template), {"tests/conftest.py": "conftest v2\n"})
    classify(pr, render=render, template=template)
    [(url, ref, data)] = render.calls
    assert (url, ref) == (str(template), "v0.1.0")
    assert "_commit" not in data
    assert "_src_path" not in data
    assert "import_path: usda.psd\n" in data
    assert "api_key_env: ''\n" in data


def test_render_failure_trusts_nothing(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), adoption(template))
    result = classify(pr, render=FakeRender({}, error="network down"), template=template)
    assert result.trusted == []
    assert any("render failed" in n and "network down" in n for n in notes(result))
    assert result.merge_class == mc.HUMAN


def test_src_path_other_than_the_family_template_trusts_nothing(
    tmp_path: Path, template: Path
) -> None:
    changes = adoption(template)
    changes[".copier-answers.yml"] = answers("https://github.com/someone/lookalike.git")
    render = FakeRender(rendered(template))
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=render, template=template)
    assert render.calls == []
    assert result.trusted == []
    assert any("not the family template" in n for n in notes(result))


def test_commit_not_on_the_template_main_trusts_nothing(tmp_path: Path, template: Path) -> None:
    changes = adoption(template)
    changes[".copier-answers.yml"] = answers(template, "rogue-tag")
    render = FakeRender(rendered(template))
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=render, template=template)
    assert render.calls == []
    assert result.trusted == []
    assert any("not on the template's main" in n for n in notes(result))


def test_no_render_trusts_nothing(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), {"tests/conftest.py": "conftest v2\n"})
    result = classify(pr)
    assert result.trusted == []
    assert any("--no-render" in n for n in notes(result))


def test_missing_answers_file_trusts_nothing(tmp_path: Path, template: Path) -> None:
    base = source_base(template)
    del base[".copier-answers.yml"]
    pr = make_pr(tmp_path, base, {"tests/conftest.py": "conftest v2\n"})
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.trusted == []
    assert any("no .copier-answers.yml" in n for n in notes(result))


# --- rules 2 and 3: adoption ---------------------------------------------------------------


def adoption(template: Path) -> dict[str, str | None]:
    """An adoption PR from template v0.1.0 to v0.2.0 that keeps every rendered file."""
    return {
        ".copier-answers.yml": answers(template),
        ".github/workflows/ci.yml": "ci v2\n",
        ".github/workflows/live.yml": "live v2\n",
        ".pre-commit-config.yaml": "hooks v2\n",
        "tests/conftest.py": "conftest v2\n",
        "CHANGELOG.md": "changelog, adopts v0.2.0\n",
    }


def test_adoption_pr_whose_workflows_match_the_render_is_auto(
    tmp_path: Path, template: Path
) -> None:
    pr = make_pr(tmp_path, source_base(template), adoption(template))
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert ".github/workflows/live.yml" in result.trusted
    assert ".pre-commit-config.yaml" in result.trusted
    assert result.remaining == ["CHANGELOG.md"]
    assert result.merge_class == mc.AUTO


def test_adoption_pr_that_edits_a_rendered_workflow_is_human(
    tmp_path: Path, template: Path
) -> None:
    changes = adoption(template)
    changes[".github/workflows/live.yml"] = "live v2, edited\n"
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.merge_class == mc.HUMAN
    assert human_rules(result) == {3}


def test_source_specific_workflow_is_human(tmp_path: Path, template: Path) -> None:
    changes = adoption(template)
    changes[".github/workflows/siblings.yml"] = "siblings\n"
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.merge_class == mc.HUMAN
    assert [f.text for f in result.findings if f.human] == [
        "protected path .github/workflows/siblings.yml (matches .github/**)"
    ]


# --- rule 3 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".claude/settings.json",
        ".pre-commit-config.yaml",
        ".secrets.baseline",
        "docs/conventions.md",
        "docs/adr/0024-something.md",
        "docs/review-checklist.md",
    ],
)
def test_protected_path_is_human(tmp_path: Path, template: Path, path: str) -> None:
    pr = make_pr(tmp_path, source_base(template), {path: "changed\n"})
    result = classify(pr)
    assert result.merge_class == mc.HUMAN
    assert human_rules(result) == {3}


@pytest.mark.parametrize(("repo", "expected"), [("xippios/sdk-core", mc.HUMAN), (SOURCE, mc.AUTO)])
def test_src_is_protected_in_core_only(tmp_path: Path, repo: str, expected: str) -> None:
    pr = make_pr(
        tmp_path,
        {"src/xippios/core/result.py": "v1\n", "pyproject.toml": PYPROJECT.format(version="1")},
        {"src/xippios/core/result.py": "v2\n"},
    )
    assert classify(pr, repo=repo).merge_class == expected


def test_every_pr_of_the_org_github_repository_is_human(tmp_path: Path) -> None:
    pr = make_pr(
        tmp_path,
        {"README.md": "stub\n", "src/keep": ""},
        {"README.md": "longer\n"},
    )
    result = classify(pr, repo="xippios/.github")
    assert result.merge_class == mc.HUMAN
    assert human_rules(result) == {3}


TEMPLATE_PYPROJECT = """\
[project]
name = "xippios-{{ source_slug }}"
version = "0.1.0"
description = "Typed client for {{ source_name }}"
dependencies = [
  "xippios-core~={{ core_version }}",
]

[project.optional-dependencies]
mcp = ["xippios-core[mcp]~={{ core_version }}"]
http = ["xippios-core[http]~={{ core_version }}"]

[project.scripts]
xippios-{{ source_slug }}-mcp = "xippios.{{ source_pkg }}.mcp:run"
{% if needs_write_tools %}
xippios-{{ source_slug }}-mcp-write = "xippios.{{ source_pkg }}.mcp_write:run"
{% endif %}
"""


def template_repo_files() -> dict[str, str | None]:
    return {
        "copier.yml": COPIER_YML,
        "template/pyproject.toml.jinja": TEMPLATE_PYPROJECT,
        "template/README.md.jinja": "readme\n",
        "tests/test_template.py": "def test(): pass\n",
    }


@pytest.mark.parametrize(
    ("old", "new", "protected"),
    [
        (
            '  "xippios-core~={{ core_version }}",\n',
            '  "xippios-core~={{ core_version }}",\n  "httpx>=0.28",\n',
            True,
        ),
        (
            'http = ["xippios-core[http]~={{ core_version }}"]\n',
            'http = ["xippios-core[http]~={{ core_version }}", "uvicorn"]\n',
            True,
        ),
        ('description = "Typed client', 'description = "A typed client', False),
    ],
    ids=["dependencies", "optional-dependencies", "description"],
)
def test_template_dependency_block_is_protected(
    tmp_path: Path, old: str, new: str, protected: bool
) -> None:
    pr = make_pr(
        tmp_path,
        template_repo_files(),
        {"template/pyproject.toml.jinja": TEMPLATE_PYPROJECT.replace(old, new)},
    )
    result = classify(pr, repo="xippios/sdk-template")
    hits = [f.text for f in result.findings if f.rule == 3]
    assert hits == (
        ["the dependency block of template/pyproject.toml.jinja changed"] if protected else []
    )


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("copier.yml", True),
        ("scripts/new-source.sh", True),
        ("template/.github/workflows/ci.yml", True),
        ("template/.claude/settings.json", True),
        ("template/.claude/commands/add-endpoint.md.jinja", True),
        ("template/.pre-commit-config.yaml", True),
        ("template/.secrets.baseline", True),
        ("template/README.md.jinja", False),
        ("tests/test_template.py", False),
    ],
)
def test_template_protected_paths(tmp_path: Path, path: str, protected: bool) -> None:
    pr = make_pr(tmp_path, template_repo_files(), {path: "changed\n"})
    result = classify(pr, repo="xippios/sdk-template")
    assert any(f.rule == 3 for f in result.findings) is protected


def test_template_has_no_root_src_so_rule_1_fires(tmp_path: Path) -> None:
    """sdk-template's own tree has no src/: rule 1, as specified, makes its every PR human."""
    pr = make_pr(tmp_path, template_repo_files(), {"template/README.md.jinja": "longer\n"})
    result = classify(pr, repo="xippios/sdk-template")
    assert human_rules(result) == {1}


# --- rule 4 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "first"),
    [
        ("__all__: list[str] = []\n", '__all__ = ["get_data"]\n', True),
        (None, '__all__ = ["get_data"]\n', True),
        ('"""No tasks yet."""\n', '__all__ = ("get_data",)\n', True),
        ('__all__ = ["get_data"]\n', '__all__ = ["get_data", "list_regions"]\n', False),
        ("__all__: list[str] = []\n", "__all__: list[str] = []\nX = 1\n", False),
    ],
    ids=["empty", "absent", "no-all", "already-public", "still-empty"],
)
def test_first_surface(
    tmp_path: Path, template: Path, before: str | None, after: str, first: bool
) -> None:
    base = source_base(template)
    base["src/xippios/usda/psd/tasks.py"] = before
    if before is None:
        del base["src/xippios/usda/psd/tasks.py"]
    pr = make_pr(tmp_path, base, {"src/xippios/usda/psd/tasks.py": after})
    result = classify(pr)
    assert (4 in human_rules(result)) is first
    assert result.merge_class == (mc.HUMAN if first else mc.AUTO)


def test_unreadable_all_is_human(tmp_path: Path, template: Path) -> None:
    pr = make_pr(
        tmp_path,
        source_base(template),
        {"src/xippios/usda/psd/tasks.py": "__all__ = sorted(globals())\n"},
    )
    result = classify(pr)
    assert human_rules(result) == {4}


# --- rule 5 ------------------------------------------------------------------------------


def release(**extra: str) -> dict[str, str | None]:
    files: dict[str, str | None] = {
        "pyproject.toml": PYPROJECT.format(version="0.2.1"),
        "uv.lock": "lock v2\n",
        "CHANGELOG.md": "## 0.2.1\n",
        "README.md": "readme 0.2.1\n",
        "CLAUDE.md": "claude 0.2.1\n",
        "docs/handover.md": "handover\n",
    }
    files.update(extra)
    return files


def test_release_pr_inside_the_subset_is_auto(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), release())
    result = classify(pr)
    assert result.merge_class == mc.AUTO


def test_release_pr_touching_tasks_is_human(tmp_path: Path, template: Path) -> None:
    changes = release(**{"src/xippios/usda/psd/tasks.py": '__all__ = ["get_data", "more"]\n'})
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr)
    assert result.merge_class == mc.HUMAN
    assert human_rules(result) == {5}
    assert "src/xippios/usda/psd/tasks.py" in next(f.text for f in result.findings if f.rule == 5)


def test_release_pr_with_a_trusted_template_file_is_auto(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), release(**{"tests/conftest.py": "conftest v2\n"}))
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.trusted == ["tests/conftest.py"]
    assert result.merge_class == mc.AUTO


def test_unchanged_version_is_no_release(tmp_path: Path, template: Path) -> None:
    pyproject = PYPROJECT.format(version="0.2.0") + "\n[tool.ruff]\nline-length = 100\n"
    pr = make_pr(
        tmp_path,
        source_base(template),
        {"pyproject.toml": pyproject, "src/xippios/usda/psd/_client.py": "x\n"},
    )
    assert classify(pr).merge_class == mc.AUTO


# --- command line ------------------------------------------------------------------------


def test_cli_writes_class_output_and_summary(
    tmp_path: Path,
    template: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pr = make_pr(tmp_path, source_base(template), {".github/workflows/extra.yml": "x\n"})
    output = tmp_path / "output"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    args = ["--repo", SOURCE, "--base", pr.base, "--head", pr.head, "--workdir", str(pr.workdir)]
    status = mc.main([*args, "--no-render", "--summary", str(summary)])
    assert status == 1
    assert output.read_text() == "class=human\n"
    assert capsys.readouterr().out.startswith("class=human\n")
    text = summary.read_text()
    assert text.startswith("## merge-class: `human`")
    assert "protected path .github/workflows/extra.yml" in text
    assert "### Remaining changed files (1)" in text


def test_cli_auto_exits_zero(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), {"tests/test_new.py": "x\n"})
    args = ["--repo", SOURCE, "--base", "main", "--head", "feature", "--workdir", str(pr.workdir)]
    assert mc.main([*args, "--no-render"]) == 0


def test_cli_bad_revision_exits_two(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), {"tests/test_new.py": "x\n"})
    args = ["--repo", SOURCE, "--base", "nope", "--head", "feature", "--workdir", str(pr.workdir)]
    assert mc.main([*args, "--no-render"]) == 2


# --- helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("README.md", "README.md", True),
        ("README.md", "src/xippios/a/reference/README.md", True),
        ("README.md", "README.md.bak", False),
        ("scripts/**", "scripts/refresh_upstream.py", True),
        ("scripts/**", "src/scripts/x.py", False),
        ("tests/test_live.py", "tests/test_live.py", True),
        ("tests/test_live.py", "x/tests/test_live.py", False),
        ("src/xippios/usda/psd/api/**", "src/xippios/usda/psd/api/A_B.py", True),
        ("src/xippios/usda/psd/api/**", "src/xippios/usda/psd/apis.py", False),
        ("docs/upstream/**", "docs/upstream/openapi/x.json", True),
        ("**/fixtures/*.json", "tests/fixtures/a.json", True),
        ("a/**/b.txt", "a/b.txt", True),
        ("a/**/b.txt", "a/x/y/b.txt", True),
        ("build/", "build/x", True),
        ("build/", "build", False),
        ("*.lock", "uv.lock", True),
        ("!README.md", "README.md", False),
    ],
)
def test_skip_pattern_semantics(pattern: str, path: str, expected: bool) -> None:
    compiled = [c for c in [mc.compile_pattern(pattern)] if c is not None]
    assert mc.matches_any(path, compiled) is expected


def test_skip_patterns_reads_block_and_flow_lists() -> None:
    assert mc.skip_patterns(COPIER_YML) == [
        "src/xippios/{{ package_dir }}/__init__.py",
        "src/xippios/{{ package_dir }}/_client.py",
        "src/xippios/{{ package_dir }}/tasks.py",
        "src/xippios/{{ package_dir }}/reference/**",
        "scripts/**",
        "tests/test_tasks.py",
        "README.md",
        "CHANGELOG.md",
    ]
    assert mc.skip_patterns("_skip_if_exists: ['a', \"b/**\"]  # inline\n") == ["a", "b/**"]
    with pytest.raises(mc.RenderError):
        mc.skip_patterns("_subdirectory: template\n")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (None, []),
        (b"x = 1\n", []),
        (b"__all__: list[str] = []\n", []),
        (b'__all__ = ["a", "b"]\n', ["a", "b"]),
        (b'__all__ = ["a"]\n__all__ += ["b"]\n', ["a", "b"]),
        (b'__all__ = ["a"]\n__all__.append("b")\n', None),
        (b"__all__ = [name for name in dir()]\n", None),
        (b'if True:\n    __all__ = ["a"]\n', None),
        (b"def broken(:\n", None),
    ],
)
def test_exported_names(source: bytes | None, expected: list[str] | None) -> None:
    assert mc.exported_names(source) == expected


def test_normalize_url() -> None:
    family = mc.normalize_url(mc.DEFAULT_TEMPLATE_URL)
    assert mc.normalize_url("https://github.com/xippios/sdk-template") == family
    assert mc.normalize_url("gh:xippios/sdk-template") == family
    assert mc.normalize_url("git@github.com:xippios/sdk-template.git") == family
    assert mc.normalize_url("https://github.com/xippios/sdk-template-fork.git") != family
