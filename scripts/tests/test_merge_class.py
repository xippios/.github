"""Tests for merge_class.py, offline: real temporary git repositories, a fake renderer.

One test per rule and per acceptance line of the merge-gate design the classifier can
prove on its own (the rulesets and identities it cannot).
"""

import os
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

# Template v0.2.0 asks more, as the real one did: rate_limit_burst and rate_limit_provenance
# with literal defaults, and here api_title with a Jinja default.
QUESTIONS_V2 = """\
rate_limit_burst:
  type: int
  help: >-
    Requests the limiter lets through at once
  default: 1

rate_limit_provenance:
  type: str
  choices:
    documented by upstream: documented
    self-imposed, upstream documents no limit: self-imposed
  default: documented

api_title:
  type: str
  default: "{{ source_slug }} API"

"""
COPIER_YML_V2 = COPIER_YML.replace("_subdirectory:", QUESTIONS_V2 + "_subdirectory:")

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
    commit(repo, {"copier.yml": COPIER_YML_V2, "CHANGELOG.md": "0.2.0\n"}, "v0.2.0")
    git(repo, "tag", "v0.2.0")
    git(repo, "checkout", "-q", "-b", "rogue")
    commit(repo, {"copier.yml": "_skip_if_exists: []\n"}, "never merged")
    git(repo, "tag", "rogue-tag")
    git(repo, "checkout", "-q", "main")
    return repo


def answers(
    src_path: Path | str,
    ref: str = "v0.2.0",
    core: str = "0.2.0",
    slug: str = "usda-psd",
    extra: str = "",
) -> str:
    return (
        "# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY\n"
        f"_commit: {ref}\n"
        f"_src_path: {src_path}\n"
        "api_key_env: ''\n"
        f"core_version: {core}\n"
        "import_path: usda.psd\n"
        f"source_slug: {slug}\n"
        f"{extra}"
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
        "src/xippios/usda/psd/http.py": "http v1\n",
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
        "src/xippios/usda/psd/http.py": "http v2\n",
        "src/xippios/usda/psd/tasks.py": "__all__: list[str] = []\n",
        "src/xippios/usda/psd/reference/README.md": "reference stub\n",
        "tests/conftest.py": "conftest v2\n",
        ".claude/commands/add-endpoint.md": "add an endpoint v2\n",
    }


class FakeRender:
    """Stands in for copier: writes fixed files, or fails like a render that cannot run."""

    def __init__(
        self,
        files: dict[str, str],
        error: str | None = None,
        executable: frozenset[str] = frozenset(),
    ) -> None:
        self.files = files
        self.error = error
        self.executable = executable
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, template_url: str, vcs_ref: str, data_file: Path, dest: Path) -> None:
        self.calls.append((template_url, vcs_ref, data_file.read_text()))
        if self.error:
            raise mc.RenderError(self.error)
        for path, content in self.files.items():
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            if path in self.executable:
                target.chmod(0o755)


def classify(
    pr: PR,
    *,
    repo: str = SOURCE,
    render: FakeRender | None = None,
    template: Path | None = None,
    core: Path | None = None,
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
        # Offline: a test that changes core_git_ref passes its fake sdk-core.
        core_url=str(core or pr.workdir.parent / "no-sdk-core"),
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
    assert human_rules(result) == {1, 4}  # no tasks.py on the base: the bootstrap too


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
    assert [f.text for f in result.findings if f.human] == [
        "src/xippios/usda/psd/mcp.py is template-owned and differs from the render"
    ]
    assert result.template_ref == "v0.1.0"  # the head's _commit
    assert result.template_sha == git(template, "rev-parse", "v0.1.0^{commit}")


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
    # The SHA the head's _commit (v0.1.0) resolves to on the template's main, not the tag.
    assert (url, ref) == (str(template), git(template, "rev-parse", "v0.1.0^{commit}"))
    assert "_commit" not in data
    assert "_src_path" not in data
    assert "import_path: usda.psd\n" in data
    assert "api_key_env: ''\n" in data


def test_copier_runs_at_the_checked_sha_without_config_or_tasks(
    tmp_path: Path, template: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real renderer, with a fake `uvx` on PATH that records its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "uvx-args"
    uvx = bin_dir / "uvx"
    uvx.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{record}"\n'
        "for dest; do :; done\n"  # the last argument: the destination
        'mkdir -p "$dest/tests"\n'
        'printf "conftest v2\\n" > "$dest/tests/conftest.py"\n'
    )
    uvx.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    pr = make_pr(tmp_path, source_base(template), {"tests/conftest.py": "conftest v2\n"})
    result = mc.classify(
        repo=SOURCE, base=pr.base, head=pr.head, workdir=pr.workdir, template_url=str(template)
    )
    args = record.read_text().splitlines()
    sha = git(template, "rev-parse", "v0.1.0^{commit}")
    assert args[:5] == ["--no-config", "--quiet", "--from", mc.COPIER_SPEC, "copier"]
    assert {"copy", "--defaults", "--trust", "--skip-tasks", "--data-file"} <= set(args)
    assert args[args.index("--vcs-ref") + 1] == sha
    assert args[-2] == str(template)
    assert result.trusted == ["tests/conftest.py"]


def test_render_failure_trusts_nothing(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), adoption(template))
    result = classify(pr, render=FakeRender({}, error="network down"), template=template)
    assert result.trusted == []
    assert any("render failed" in n and "network down" in n for n in notes(result))
    assert result.merge_class == mc.HUMAN


def test_failed_template_clone_trusts_nothing(tmp_path: Path, template: Path) -> None:
    """The real clone fails (no repository at the URL): no render, no _commit check."""
    changes = adoption(template)
    changes[".copier-answers.yml"] = answers(tmp_path / "missing")
    render = FakeRender(rendered(template))
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=render, template=tmp_path / "missing")
    assert render.calls == []
    assert result.trusted == []
    assert any("render failed" in n and "cannot clone" in n for n in notes(result))
    assert "_commit changes from v0.1.0 to v0.2.0, not checked against the template" in [
        f.text for f in result.findings if f.human
    ]


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


def test_commit_that_is_not_a_plain_ref_trusts_nothing(tmp_path: Path, template: Path) -> None:
    changes = adoption(template)
    changes[".copier-answers.yml"] = answers(template, "--upload-pack=touch")
    render = FakeRender(rendered(template))
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=render, template=template)
    assert render.calls == []
    assert any("not a plain git ref" in n for n in notes(result))


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


@pytest.mark.parametrize("side", ["head", "render"])
def test_a_mode_only_difference_is_not_trusted(tmp_path: Path, template: Path, side: str) -> None:
    """Rule 2 compares the executable bit too: 100755 against 100644 is no match."""
    path = "tests/conftest.py"
    pr = make_pr(tmp_path, source_base(template), {path: "conftest v2\n"})
    if side == "head":
        (pr.workdir / path).chmod(0o755)
        pr.head = commit(pr.workdir, {}, "chmod +x")
    render = FakeRender(
        rendered(template), executable=frozenset({path} if side == "render" else ())
    )
    result = classify(pr, render=render, template=template)
    assert result.trusted == []
    assert result.remaining == [path]


def test_a_symlink_at_a_template_owned_path_is_never_trusted(
    tmp_path: Path, template: Path
) -> None:
    path = "tests/conftest.py"
    pr = make_pr(tmp_path, source_base(template), {"tests/real.py": "conftest v2\n"})
    (pr.workdir / path).unlink()
    (pr.workdir / path).symlink_to("real.py")
    pr.head = commit(pr.workdir, {}, "symlink")
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert path in result.remaining
    assert path not in result.trusted


def test_a_path_that_is_not_plain_is_never_trusted_and_reported(
    tmp_path: Path, template: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git writes no such path; a crafted tree could. The render's ../escape is never read."""
    real = mc.changed_files
    odd = ["../escape", "/etc/passwd", "tests//conftest.py", "tests/./conftest.py"]
    monkeypatch.setattr(mc, "changed_files", lambda *args: sorted([*real(*args), *odd]))
    files = {**rendered(template), "../escape": "conftest v2\n"}
    pr = make_pr(tmp_path, source_base(template), {"tests/conftest.py": "conftest v2\n"})
    result = classify(pr, render=FakeRender(files), template=template)
    assert result.trusted == ["tests/conftest.py"]
    assert sorted(f.text for f in result.findings if f.human) == sorted(
        f"{path} is no plain relative path; never trusted" for path in odd
    )


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


# --- rule 2: the answers file ------------------------------------------------------------


def test_answer_change_other_than_the_free_keys_is_human(tmp_path: Path, template: Path) -> None:
    changes = adoption(template)
    changes[".copier-answers.yml"] = answers(template, slug="usda-psd2")
    files = rendered(template)
    files[".copier-answers.yml"] = answers(template, slug="usda-psd2")
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=FakeRender(files), template=template)
    assert ".copier-answers.yml" in result.trusted  # the render writes the answers back
    assert [f.text for f in result.findings if f.human] == ["answers changed: source_slug"]


def test_commit_moving_backward_is_human(tmp_path: Path, template: Path) -> None:
    base = source_base(template)
    base[".copier-answers.yml"] = answers(template, "v0.2.0")
    files = rendered(template)
    files[".copier-answers.yml"] = answers(template, "v0.1.0")
    pr = make_pr(tmp_path, base, {".copier-answers.yml": answers(template, "v0.1.0")})
    result = classify(pr, render=FakeRender(files), template=template)
    assert result.trusted == [".copier-answers.yml"]
    assert [f.text for f in result.findings if f.human] == [
        "_commit changes from v0.2.0 to v0.1.0, not forward along the template's main"
    ]


@pytest.mark.parametrize("render", [False, True], ids=["no-render", "render"])
def test_core_version_bump_alone_is_auto(tmp_path: Path, template: Path, render: bool) -> None:
    head_answers = answers(template, "v0.1.0", core="0.2.1")
    files = rendered(template)
    files[".copier-answers.yml"] = head_answers
    pr = make_pr(tmp_path, source_base(template), {".copier-answers.yml": head_answers})
    result = classify(pr, render=FakeRender(files) if render else None, template=template)
    assert result.merge_class == mc.AUTO
    assert result.trusted == ([".copier-answers.yml"] if render else [])


def test_commit_moving_forward_with_a_core_bump_is_auto(tmp_path: Path, template: Path) -> None:
    changes = adoption(template)
    changes[".copier-answers.yml"] = answers(template, "v0.2.0", core="0.2.1")
    files = rendered(template)
    files[".copier-answers.yml"] = changes[".copier-answers.yml"] or ""
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=FakeRender(files), template=template)
    assert result.merge_class == mc.AUTO


def test_commit_change_without_the_template_is_human(tmp_path: Path, template: Path) -> None:
    """Under --no-render nothing can show that _commit moved forward."""
    pr = make_pr(tmp_path, source_base(template), adoption(template))
    result = classify(pr)
    assert [f.text for f in result.findings if f.human and f.rule == 2] == [
        "_commit changes from v0.1.0 to v0.2.0, not checked against the template"
    ]


NON_DEFAULT = "answers added with non-default values: "


@pytest.mark.parametrize(
    ("added", "reasons"),
    [
        ("rate_limit_burst: 1\n", []),
        ("rate_limit_provenance: 'documented'\n", []),
        ("rate_limit_burst: 2\n", [NON_DEFAULT + "rate_limit_burst"]),
        ("rate_limit_burst: '1'\n", [NON_DEFAULT + "rate_limit_burst"]),
        ("rate_limit_burst:1\n", [NON_DEFAULT + "rate_limit_burst"]),
        ("api_title: usda-psd API\n", [NON_DEFAULT + "api_title"]),
        ("api_title: '{{ source_slug }} API'\n", [NON_DEFAULT + "api_title"]),
        ("not_asked: x\n", [NON_DEFAULT + "not_asked"]),
        (
            "rate_limit_burst: 1\nrate_limit_provenance: self-imposed\n",
            [NON_DEFAULT + "rate_limit_provenance"],
        ),
    ],
    ids=[
        "default",
        "default-quoted",
        "other-value",
        "string-for-int",
        "no-space",
        "jinja-default",
        "jinja-default-text",
        "unknown-question",
        "psd-7",
    ],
)
def test_answer_a_template_release_adds_is_free_only_at_its_literal_default(
    tmp_path: Path, template: Path, added: str, reasons: list[str]
) -> None:
    """psd #7: v0.2.0 added rate_limit_burst (1, the default) and rate_limit_provenance."""
    changes = adoption(template)
    changes[".copier-answers.yml"] = answers(template, extra=added)
    files = rendered(template)
    files[".copier-answers.yml"] = answers(template, extra=added)
    pr = make_pr(tmp_path, source_base(template), changes)
    result = classify(pr, render=FakeRender(files), template=template)
    assert [f.text for f in result.findings if f.human] == reasons
    assert result.merge_class == (mc.HUMAN if reasons else mc.AUTO)


def test_an_added_answer_is_judged_by_the_template_at_the_heads_commit(
    tmp_path: Path, template: Path
) -> None:
    """v0.1.0 does not ask rate_limit_burst: added on a head at v0.1.0, it is no default."""
    head_answers = answers(template, "v0.1.0", extra="rate_limit_burst: 1\n")
    files = rendered(template)
    files[".copier-answers.yml"] = head_answers
    pr = make_pr(tmp_path, source_base(template), {".copier-answers.yml": head_answers})
    result = classify(pr, render=FakeRender(files), template=template)
    assert [f.text for f in result.findings if f.human] == [NON_DEFAULT + "rate_limit_burst"]


def test_an_added_answer_without_the_template_is_human(tmp_path: Path, template: Path) -> None:
    head_answers = answers(template, "v0.1.0", extra="rate_limit_burst: 1\n")
    pr = make_pr(tmp_path, source_base(template), {".copier-answers.yml": head_answers})
    result = classify(pr)
    assert [f.text for f in result.findings if f.human] == [
        "answers added, not checked against the template: rate_limit_burst"
    ]


@dataclass
class Core:
    path: Path
    on_main: str
    off_main: str


@pytest.fixture
def core(tmp_path: Path) -> Core:
    """A fake sdk-core: two commits on main, v0.2.1 on the first, `feature` off main."""
    repo = tmp_path / "sdk-core"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    first = commit(repo, {"README.md": "core\n"}, "first")
    git(repo, "tag", "v0.2.1")
    commit(repo, {"README.md": "core 2\n"}, "second")
    git(repo, "checkout", "-q", "-b", "feature")
    off = commit(repo, {"README.md": "off main\n"}, "off main")
    git(repo, "tag", "rogue")
    git(repo, "tag", "v9.9.9-rc")
    git(repo, "checkout", "-q", "main")
    return Core(repo, first, off)


@pytest.mark.parametrize(
    ("ref", "free"),
    [
        ("main", True),
        ("on_main", True),
        ("on_main_short", True),
        ("v0.2.1", True),
        ("v9.9.9-rc", True),  # a v* tag, wherever it points
        ("''", True),
        ("off_main", False),
        ("feature", False),
        ("rogue", False),
        ("missing", False),
        ("--upload-pack=touch", False),
    ],
)
def test_core_pin_must_be_on_core_main_or_a_v_tag(
    tmp_path: Path, template: Path, core: Core, ref: str, free: bool
) -> None:
    value = {
        "on_main": core.on_main,
        "on_main_short": core.on_main[:12],
        "off_main": core.off_main,
    }.get(ref, ref)
    head_answers = answers(template, "v0.1.0", extra=f"core_git_ref: {value}\n")
    files = rendered(template)
    files[".copier-answers.yml"] = head_answers
    pr = make_pr(tmp_path, source_base(template), {".copier-answers.yml": head_answers})
    result = classify(pr, render=FakeRender(files), template=template, core=core.path)
    reason = (
        f"core pinned off main: core_git_ref {value} is no commit on sdk-core's main and no v* tag"
    )
    assert [f.text for f in result.findings if f.human] == ([] if free else [reason])


def test_core_pin_without_the_check_is_human(tmp_path: Path, template: Path) -> None:
    head_answers = answers(template, "v0.1.0", extra="core_git_ref: main\n")
    files = rendered(template)
    files[".copier-answers.yml"] = head_answers
    pr = make_pr(tmp_path, source_base(template), {".copier-answers.yml": head_answers})
    no_render = classify(pr)
    assert [f.text for f in no_render.findings if f.human] == [
        "core_git_ref changes to main, not checked against sdk-core"
    ]
    failed = classify(pr, render=FakeRender(files), template=template)  # no sdk-core there
    [text] = [f.text for f in failed.findings if f.human]
    assert text.startswith("core_git_ref main not checked against sdk-core: cannot clone")


@pytest.mark.parametrize(
    ("pin", "render", "human"),
    [
        ("feature", True, True),  # off main: every pull request is human until it is lifted
        ("main", True, False),
        ("feature", False, False),  # --no-render judges only a change of the pin
    ],
)
def test_a_pin_the_pull_request_does_not_change_is_checked_too(
    tmp_path: Path, template: Path, core: Core, pin: str, render: bool, human: bool
) -> None:
    base = source_base(template)
    base[".copier-answers.yml"] = answers(template, "v0.1.0", extra=f"core_git_ref: {pin}\n")
    pr = make_pr(tmp_path, base, {"tests/test_new.py": "x\n"})
    renderer = FakeRender(rendered(template)) if render else None
    result = classify(pr, render=renderer, template=template, core=core.path)
    reason = (
        f"core pinned off main: core_git_ref {pin} is no commit on sdk-core's main and no v* tag"
    )
    assert [f.text for f in result.findings if f.human] == ([reason] if human else [])


def test_a_removed_or_emptied_core_pin_is_free(tmp_path: Path, template: Path) -> None:
    base = source_base(template)
    base[".copier-answers.yml"] = answers(template, "v0.1.0", extra="core_git_ref: feature\n")
    for root, extra in (("removed", ""), ("emptied", "core_git_ref: ''\n")):
        (tmp_path / root).mkdir()
        head_answers = answers(template, "v0.1.0", core="0.2.1", extra=extra)
        pr = make_pr(tmp_path / root, base, {".copier-answers.yml": head_answers})
        assert classify(pr).merge_class == mc.AUTO


def test_question_defaults() -> None:
    text = """\
# a comment
plain:
  type: int
  default: 1
quoted:
  type: str
  default: "documented"  # a comment
short: ''
jinja:
  default: "{{ other }}"
block:
  default: >-
    folded
nested:
  choices:
    default: not-this-one
  help: >-
    default: nor this
missing:
  type: str
twice:
  default: a
twice:
  default: a
flow: {type: str, default: x}
escaped:
  default: "a\\tb"
_settings: ignored
"""
    assert mc.question_defaults(text) == {
        "plain": mc.Scalar("1", quoted=False),
        "quoted": mc.Scalar("documented", quoted=True),
        "short": mc.Scalar("", quoted=True),
        "jinja": None,
        "block": None,
        "nested": None,
        "missing": None,
        "twice": None,
        "flow": None,
        "escaped": None,
    }


@pytest.mark.parametrize(
    ("answer", "default", "same"),
    [
        ("1", "1", True),
        ("documented", '"documented"', True),
        ("''", '""', True),
        ("'it''s'", '"it\'s"', True),
        ("'1'", "1", False),
        ("true", '"true"', False),
        ("documented", "self-imposed", False),
    ],
)
def test_literals_compare_as_yaml_loads_them(answer: str, default: str, same: bool) -> None:
    left, right = mc.literal_scalar(answer), mc.literal_scalar(default)
    assert left is not None
    assert right is not None
    assert left.same(right) is same


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
        "docs/definition-of-done.md",
        ".claude/settings.local.json",
        ".claude/agents/reviewer.md",
        ".claude/hooks/guard.py",
        ".claude/commands/add-endpoint.md",
        ".mcp.json",
        "CLAUDE.local.md",
    ],
)
def test_protected_path_is_human(tmp_path: Path, template: Path, path: str) -> None:
    pr = make_pr(tmp_path, source_base(template), {path: "changed\n"})
    result = classify(pr)
    assert result.merge_class == mc.HUMAN
    assert human_rules(result) == {3}


@pytest.mark.parametrize(
    "repo", [SOURCE, "xippios/sdk-core", "xippios/sdk-template", "xippios/.github", "xippios/x"]
)
def test_commands_are_protected_in_every_repository(
    tmp_path: Path, template: Path, repo: str
) -> None:
    """sdk-core's and sdk-template's own commands too, not only the ones a source renders."""
    path = ".claude/commands/release-prep.md"
    pr = make_pr(tmp_path, source_base(template), {path: "changed\n"})
    result = classify(pr, repo=repo)
    assert human_rules(result) == {3}
    assert f"protected path {path} (matches .claude/commands/**)" in [
        f.text for f in result.findings if f.human
    ]


def test_rendered_command_is_trusted_when_identical_and_human_when_edited(
    tmp_path: Path, template: Path
) -> None:
    path = ".claude/commands/add-endpoint.md"
    for content, expected in (("add an endpoint v2\n", mc.AUTO), ("edited by hand\n", mc.HUMAN)):
        root = tmp_path / expected
        root.mkdir()
        pr = make_pr(root, source_base(template), {path: content})
        result = classify(pr, render=FakeRender(rendered(template)), template=template)
        assert result.merge_class == expected
        assert (path in result.trusted) is (expected == mc.AUTO)


@pytest.mark.parametrize(
    ("path", "content", "human"),
    [
        ("src/xippios/usda/psd/mcp.py", "mcp v2, edited\n", True),
        ("src/xippios/usda/psd/http.py", None, True),  # deleted
        ("src/xippios/usda/psd/_client.py", "client, fixed\n", False),  # skip-listed
        ("src/xippios/usda/psd/models.py", "models\n", False),  # not rendered
    ],
)
def test_template_owned_src_file_that_differs_from_the_render_is_human(
    tmp_path: Path, template: Path, path: str, content: str | None, human: bool
) -> None:
    """Rule 3: an adapter changed by hand could expose tasks around rule 4."""
    pr = make_pr(tmp_path, source_base(template), {path: content})
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert human_rules(result) == ({3} if human else set())


@pytest.mark.parametrize(
    ("path", "human"),
    [
        ("src/xippios/usda/psd/mcp.py", True),
        ("src/xippios/usda/psd/http.py", True),
        ("src/xippios/usda/psd/_version.py", True),
        ("src/xippios/usda/psd/api/__init__.py", True),
        ("src/xippios/usda/psd/api/get_data.py", False),
        ("src/xippios/usda/psd/_client.py", False),
    ],
)
def test_without_a_render_the_adapters_are_template_owned_by_name(
    tmp_path: Path, template: Path, path: str, human: bool
) -> None:
    pr = make_pr(tmp_path, source_base(template), {path: "edited\n"})
    result = classify(pr)
    assert human_rules(result) == ({3} if human else set())


@pytest.mark.parametrize(("repo", "expected"), [("xippios/sdk-core", mc.HUMAN), (SOURCE, mc.AUTO)])
def test_src_is_protected_in_core_only(tmp_path: Path, repo: str, expected: str) -> None:
    pr = make_pr(
        tmp_path,
        {
            "src/xippios/core/result.py": "v1\n",
            "src/xippios/core/tasks.py": '__all__ = ["get"]\n',  # no bootstrap in a source
            "pyproject.toml": PYPROJECT.format(version="1"),
        },
        {"src/xippios/core/result.py": "v2\n"},
    )
    assert classify(pr, repo=repo).merge_class == expected


def test_every_pr_of_the_org_github_repository_is_human(tmp_path: Path) -> None:
    pr = make_pr(tmp_path, {"README.md": "stub\n"}, {"README.md": "longer\n"})
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

[dependency-groups]
dev = [
  "pytest>=8",
]

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100

[tool.uv.sources]
{% if core_git_ref %}
xippios-core = { git = "https://github.com/xippios/sdk-core", rev = "{{ core_git_ref }}" }
{% endif %}
"""


def template_repo_files() -> dict[str, str | None]:
    return {
        "copier.yml": COPIER_YML,
        "template/pyproject.toml.jinja": TEMPLATE_PYPROJECT,
        "template/README.md.jinja": "readme\n",
        "tests/test_template.py": "def test(): pass\n",
    }


BLOCK = "the dependency block of template/pyproject.toml.jinja changed"
JINJA_LINE = "a line that carries Jinja changed in template/pyproject.toml.jinja"


@pytest.mark.parametrize(
    ("old", "new", "hits"),
    [
        (
            '  "xippios-core~={{ core_version }}",\n',
            '  "xippios-core~={{ core_version }}",\n  "httpx>=0.28",\n',
            [BLOCK],
        ),
        (
            'http = ["xippios-core[http]~={{ core_version }}"]\n',
            'http = ["xippios-core[http]~={{ core_version }}", "uvicorn"]\n',
            [BLOCK, JINJA_LINE],
        ),
        ('  "pytest>=8",\n', '  "pytest>=8",\n  "evil-plugin",\n', [BLOCK]),
        (
            'rev = "{{ core_git_ref }}"',
            'rev = "{{ core_git_ref }}", subdirectory = "x"',
            [BLOCK, JINJA_LINE],
        ),
        ("[tool.uv.sources]\n", "[tool.uv.sources]\nother = { path = '../other' }\n", [BLOCK]),
        ('requires = ["hatchling>=1.27"]', 'requires = ["hatchling>=1.27", "evil"]', [BLOCK]),
        ("[tool.ruff]\n", '[[tool.uv.index]]\nurl = "https://x.invalid"\n\n[tool.ruff]\n', [BLOCK]),
        ("[tool.ruff]\n", '[tool.uv]\noverride-dependencies = ["a"]\n\n[tool.ruff]\n', [BLOCK]),
        ("[tool.ruff]\n", '[tool.uv]\nindex-url = "https://x.invalid"\n\n[tool.ruff]\n', [BLOCK]),
        ("[project.scripts]\n", '[project.scripts]\nevil = "os:system"\n', [BLOCK]),
        (
            "[dependency-groups]\n",
            '[project.entry-points.pytest11]\nplugin = "x.y"\n\n[dependency-groups]\n',
            [BLOCK],
        ),
        ('description = "Typed client', 'description = "A typed client', [JINJA_LINE]),
        ("line-length = 100\n", 'line-length = 100\nsrc = ["{{ source_slug }}"]\n', [JINJA_LINE]),
        ("{% endif %}\n\n[dependency-groups]", "\n[dependency-groups]", [BLOCK, JINJA_LINE]),
        ("line-length = 100", "line-length = 120", []),
    ],
    ids=[
        "dependencies",
        "optional-dependencies",
        "dependency-groups",
        "uv-sources",
        "uv-sources-added",
        "build-system",
        "uv-index",
        "uv-override-dependencies",
        "uv-index-url",
        "scripts",
        "entry-points",
        "jinja-description",
        "jinja-line-added",
        "jinja-line-removed",
        "tool-ruff",
    ],
)
def test_template_dependency_block_and_jinja_lines_are_protected(
    tmp_path: Path, old: str, new: str, hits: list[str]
) -> None:
    assert old in TEMPLATE_PYPROJECT
    pr = make_pr(
        tmp_path,
        template_repo_files(),
        {"template/pyproject.toml.jinja": TEMPLATE_PYPROJECT.replace(old, new, 1)},
    )
    result = classify(pr, repo="xippios/sdk-template")
    assert [f.text for f in result.findings if f.rule == 3] == hits


SOURCE_PYPROJECT = (
    PYPROJECT.format(version="0.2.0")
    + """
[project.scripts]
xippios-usda-psd-mcp = "xippios.usda.psd.mcp:run"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
"""
)


@pytest.mark.parametrize(
    ("old", "new", "tables"),
    [
        (
            'requires = ["hatchling>=1.27"]',
            'requires = ["hatchling>=1.27", "evil"]',
            "build-system",
        ),
        ("[tool.ruff]", '[[tool.uv.index]]\nurl = "https://x.invalid"\n\n[tool.ruff]', "tool.uv"),
        ("[tool.ruff]", '[tool.uv]\nindex-url = "https://x.invalid"\n\n[tool.ruff]', "tool.uv"),
        ("[tool.ruff]", '[tool.uv.sources]\nx = { path = "../x" }\n\n[tool.ruff]', "tool.uv"),
        ("[tool.ruff]", '[tool.uv]\noverride-dependencies = ["a"]\n\n[tool.ruff]', "tool.uv"),
        ('mcp:run"', 'mcp:run"\nevil = "os:system"', "project.scripts"),
        (
            "[build-system]",
            '[project.gui-scripts]\ng = "x:y"\n\n[build-system]',
            "project.gui-scripts",
        ),
        (
            "[build-system]",
            '[project.entry-points.pytest11]\np = "x.y"\n\n[build-system]',
            "project.entry-points",
        ),
        ('"xippios-core~=0.2.0"', '"xippios-core~=0.2.0", "httpx>=0.28"', None),
        ('dev = ["pytest>=8"]', 'dev = ["pytest>=8", "respx"]', None),
        ("line-length = 100", "line-length = 120", None),
    ],
    ids=[
        "build-system",
        "uv-index",
        "uv-index-url",
        "uv-sources",
        "uv-override-dependencies",
        "scripts",
        "gui-scripts",
        "entry-points",
        "dependencies",
        "dependency-groups",
        "tool-ruff",
    ],
)
def test_build_and_install_routes_of_a_pyproject_are_protected(
    tmp_path: Path, template: Path, old: str, new: str, tables: str | None
) -> None:
    assert old in SOURCE_PYPROJECT
    base = source_base(template)
    base["pyproject.toml"] = SOURCE_PYPROJECT
    pr = make_pr(tmp_path, base, {"pyproject.toml": SOURCE_PYPROJECT.replace(old, new, 1)})
    result = classify(pr)
    expected = [f"build or install routes changed in pyproject.toml: {tables}"] if tables else []
    assert [f.text for f in result.findings if f.human] == expected


@pytest.mark.parametrize("repo", ["xippios/sdk-core", "xippios/sdk-template"])
def test_build_routes_are_protected_in_every_repository(tmp_path: Path, repo: str) -> None:
    base = {"pyproject.toml": SOURCE_PYPROJECT, "README.md": "x\n"}
    head = SOURCE_PYPROJECT.replace('build-backend = "hatchling.build"', 'build-backend = "evil"')
    pr = make_pr(tmp_path, base, {"pyproject.toml": head})
    result = classify(pr, repo=repo)
    assert [f.text for f in result.findings if f.human] == [
        "build or install routes changed in pyproject.toml: build-system"
    ]


def test_an_unreadable_pyproject_is_human(tmp_path: Path, template: Path) -> None:
    pr = make_pr(tmp_path, source_base(template), {"pyproject.toml": "[project\n"})
    result = classify(pr)
    assert any(
        f.rule == 3 and f.text.startswith("cannot read the build and install tables")
        for f in result.findings
    )


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("copier.yml", True),
        ("copier.yaml", True),
        ("scripts/new-source.sh", True),
        ("template/.github/workflows/ci.yml", True),
        ("template/.github/workflows/live.yml.jinja", True),
        ("template/.claude/settings.json", True),
        ("template/.claude/settings.local.json", True),
        ("template/.claude/agents/reviewer.md.jinja", True),
        ("template/.claude/hooks/guard.py", True),
        ("template/.claude/commands/add-endpoint.md.jinja", True),
        ("template/.mcp.json.jinja", True),
        ("template/CLAUDE.local.md", True),
        ("template/.pre-commit-config.yaml", True),
        ("template/.secrets.baseline", True),
        ("template/docs/conventions.md", True),
        ("template/docs/adr/0001-layers.md", True),
        ("template/docs/review-checklist.md.jinja", True),
        ("template/docs/definition-of-done.md", True),
        ("template/src/xippios/{{ package_dir }}/mcp.py.jinja", True),  # Jinja in the name
        ("template/{{ _copier_conf.answers_file }}.jinja", True),
        ("template/{% if x %}.github{% endif %}/ci.yml", True),
        ("template/README.md.jinja", False),
        ("template/docs/upstream/FETCHED.md.jinja", False),
        ("tests/test_template.py", False),
    ],
)
def test_template_protected_paths(tmp_path: Path, path: str, protected: bool) -> None:
    """sdk-template skips rule 1, so its rule-3 list alone decides: the list is reachable."""
    pr = make_pr(tmp_path, template_repo_files(), {path: "changed\n"})
    result = classify(pr, repo="xippios/sdk-template")
    assert human_rules(result) == ({3} if protected else set())
    assert result.merge_class == (mc.HUMAN if protected else mc.AUTO)


@pytest.mark.parametrize(
    ("repo", "rules"),
    [
        (SOURCE, {1}),
        ("xippios/sdk-template", set()),
        ("xippios/sdk-core", set()),
        ("xippios/.github", {3}),  # every PR there is human, by rule 3 alone
        ("xippios/other", set()),
    ],
)
def test_rule_1_applies_to_source_repositories_only(
    tmp_path: Path, repo: str, rules: set[int]
) -> None:
    """A base without src/ is a scaffold only in a source; sdk-template and .github have none."""
    pr = make_pr(tmp_path, template_repo_files(), {"template/README.md.jinja": "longer\n"})
    result = classify(pr, repo=repo)
    assert human_rules(result) == rules


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
    texts = [f.text for f in result.findings if f.human]
    assert any(text.startswith("first surface:") for text in texts) is first
    # A base that exports nothing is still in its bootstrap: any change under src/ is human.
    bootstrap = before is None or "get_data" not in before
    assert result.merge_class == (mc.HUMAN if first or bootstrap else mc.AUTO)


@pytest.mark.parametrize(
    ("tasks", "repo", "human"),
    [
        ("__all__: list[str] = []\n", SOURCE, True),
        (None, SOURCE, True),
        ("__all__ = sorted(globals())\n", SOURCE, True),  # unreadable exports nothing known
        ('__all__ = ["get_data"]\n', SOURCE, False),
        ("__all__: list[str] = []\n", "xippios/sdk-core", False),
    ],
    ids=["empty", "absent", "unreadable", "exports", "not-a-source"],
)
def test_bootstrap_makes_every_src_change_human(
    tmp_path: Path, template: Path, tasks: str | None, repo: str, human: bool
) -> None:
    """Rule 4's static reading has limits; while the base exports no task, src/ is human."""
    base = source_base(template)
    base["src/xippios/usda/psd/tasks.py"] = tasks
    if tasks is None:
        del base["src/xippios/usda/psd/tasks.py"]
    changes: dict[str, str | None] = {
        "src/xippios/usda/psd/models.py": "models\n",
        "tests/test_models.py": "ok\n",
    }
    pr = make_pr(tmp_path, base, changes)
    result = classify(pr, repo=repo)
    texts = [f.text for f in result.findings if f.human and f.rule == 4]
    expected = "bootstrap: no tasks.py on the base exports a task, and src/ changes: "
    assert texts == ([expected + "src/xippios/usda/psd/models.py"] if human else [])


def test_bootstrap_spares_a_src_file_identical_to_the_render(
    tmp_path: Path, template: Path
) -> None:
    base = source_base(template)
    base["src/xippios/usda/psd/tasks.py"] = "__all__: list[str] = []\n"
    pr = make_pr(tmp_path, base, {"src/xippios/usda/psd/mcp.py": "mcp v2\n"})
    result = classify(pr, render=FakeRender(rendered(template)), template=template)
    assert result.trusted == ["src/xippios/usda/psd/mcp.py"]
    assert result.merge_class == mc.AUTO


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


def test_release_pr_with_check_siblings_is_auto(tmp_path: Path, template: Path) -> None:
    """scripts/check-siblings.sh belongs to the release subset until the template owns it."""
    changes = release(**{"scripts/check-siblings.sh": "#!/bin/sh\nexit 0\n"})
    pr = make_pr(tmp_path, source_base(template), changes)
    assert classify(pr).merge_class == mc.AUTO


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


# --- inputs and reasons ------------------------------------------------------------------


def test_the_branch_name_is_no_input(tmp_path: Path, template: Path) -> None:
    """The class depends on the two commits alone: a release-shaped name changes nothing."""
    pr = make_pr(tmp_path, source_base(template), {".github/workflows/extra.yml": "x\n"})
    results = []
    for branch in ("fix/extra", "chore/release-9.9.9", "chore/template-update-v9"):
        git(pr.workdir, "branch", "-f", branch, pr.head)
        results.append(classify(PR(pr.workdir, "main", branch)))
    assert {
        (r.head, r.merge_class, tuple(f.text for f in r.findings if f.human)) for r in results
    } == {
        (
            pr.head,
            mc.HUMAN,
            ("protected path .github/workflows/extra.yml (matches .github/**)",),
        )
    }
    assert "branch" not in mc.classify.__code__.co_varnames


def test_a_pr_behind_its_base_is_compared_with_the_merge_base(
    tmp_path: Path, template: Path
) -> None:
    """main moved on (a protected file) after the branch forked: not the PR's change."""
    pr = make_pr(tmp_path, source_base(template), {"tests/test_new.py": "x\n"})
    git(pr.workdir, "checkout", "-q", "main")
    tip = commit(pr.workdir, {".github/workflows/ci.yml": "ci v9\n"}, "main moves on")
    result = classify(PR(pr.workdir, tip, pr.head))
    assert result.base == tip
    assert result.merge_base == pr.base != tip
    assert result.changed == ["tests/test_new.py"]
    assert result.merge_class == mc.AUTO


def test_every_reason_is_reported(tmp_path: Path, template: Path) -> None:
    """The first human decides the class; the later rules still report theirs."""
    base = source_base(template)
    base["src/xippios/usda/psd/tasks.py"] = "__all__: list[str] = []\n"
    changes = release(**{"src/xippios/usda/psd/tasks.py": '__all__ = ["get_data"]\n'})
    changes[".github/workflows/extra.yml"] = "x\n"
    pr = make_pr(tmp_path, base, changes)
    result = classify(pr)
    assert [f.rule for f in result.findings if f.human] == [
        3,
        4,
        4,
        5,
    ]  # 4: first surface, bootstrap


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


def test_file_names_are_escaped_in_the_summary_and_the_report(
    tmp_path: Path,
    template: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    name = ".github/evil`name\n- rule 6: no rule says human.yml"
    pr = make_pr(tmp_path, source_base(template), {name: "x\n"})
    summary = tmp_path / "summary.md"
    args = ["--repo", SOURCE, "--base", pr.base, "--head", pr.head, "--workdir", str(pr.workdir)]
    assert mc.main([*args, "--no-render", "--summary", str(summary)]) == 1
    escaped = ".github/evil\\x60name\\x0a- rule 6: no rule says human.yml"
    out = capsys.readouterr().out
    text = summary.read_text()
    for report in (out, text):
        assert escaped in report
        assert "\n- rule 6" not in report
    assert f"- `{escaped}`" in text


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
        (b'__all__: list[str] = []\n"""Docs that mention __all__ in passing."""\n', []),
    ],
)
def test_exported_names(source: bytes | None, expected: list[str] | None) -> None:
    assert mc.exported_names(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "from ._impl import __all__\n",
        "from ._impl import names as __all__\n",
        "import _impl as __all__\n",
        "from ._impl import *\n",
        'def __getattr__(name):\n    return ["get_data"]\n',
        "__getattr__ = lambda name: []\n",
        'globals()["__all__"] = ["get_data"]\n',
        'import sys\nsetattr(sys.modules[__name__], "__all__", ["get_data"])\n',
        'NAME = "__all__"\n',
        'vars()["__al" + "l__"] = ["get_data"]\n',
        "import sys\nsys.modules[__name__].__dict__.update(x=1)\n",
        '__all__: list[str] = []\nalias = __all__\nalias.append("get_data")\n',
        'def __all__():\n    return ["get_data"]\n',
        'for __all__ in [["get_data"]]:\n    pass\n',
        "__all__ = []\ndel __all__\n",
        '__all__ = []\n(__all__ := ["get_data"])\n',
    ],
)
def test_all_that_cannot_be_read_statically_is_unreadable(source: str) -> None:
    assert mc.exported_names(source.encode()) is None


def test_normalize_url() -> None:
    family = mc.normalize_url(mc.DEFAULT_TEMPLATE_URL)
    assert mc.normalize_url("https://github.com/xippios/sdk-template") == family
    assert mc.normalize_url("gh:xippios/sdk-template") == family
    assert mc.normalize_url("git@github.com:xippios/sdk-template.git") == family
    assert mc.normalize_url("https://github.com/xippios/sdk-template-fork.git") != family
