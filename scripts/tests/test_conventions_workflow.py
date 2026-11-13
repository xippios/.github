"""The conventions review runs by mode on any repository's documents (C57 as amended by
coordinate-core#364, .github#32). The job's own `if:` skips a pull request that is no release's
and that no other mode could review, so the caller's check reports as skipped and passing
(.github#47). The step `Gate` of conventions.yml then decides from the caller's
`CONVENTIONS_REVIEW` variable, the pull request's label `release` and its title whether the
review runs, before any checkout or API call; the step `Verdict` writes the check's comment in
the style of docs/style/reviews.md on every run that reviewed the pull request, `ready` included
(.github#36). The tests run the steps' own scripts."""

import json
import os
import subprocess
from pathlib import Path

import conventions as fr
import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "conventions.yml").read_text()
README = (ROOT / "README.md").read_text()
MODES = ("release", "all", "off")
# A release PR's title, `<version> Release`, and `release: <version>` until every workspace has
# adopted coordinate-core 0.7.4 (coordinate-core#805), as the core's `RELEASE_TITLE` reads it.
RELEASE_TITLES = ["0.7.4 Release", "release: 0.6.4", "release: 0.6.4-rc.1", "release: v0.6.4"]
OTHER_TITLES = [
    "feat: a change",
    "Release: 0.6.4",
    "release: 0.6.4 and more",
    "release 0.6.4",
    "release: notes",
    "v0.7.4 Release",
    "0.7.4 release",
    "0.7.4-rc.1 Release",
    "0.7.4 Release notes",
    "Plan the Release",
]
# The job's own condition (.github#47), its folded lines joined as YAML folds them.
CONDITION = (
    "contains(github.event.pull_request.labels.*.name, 'release') "
    "|| startsWith(github.event.pull_request.title, 'release: ') "
    "|| endsWith(github.event.pull_request.title, ' Release') "
    "|| (vars.CONVENTIONS_REVIEW != '' && vars.CONVENTIONS_REVIEW != 'release' "
    "&& vars.CONVENTIONS_REVIEW != 'off')"
)
REPO = "xippios/sdk-usda-psd"
SHA = "c" * 40
COMMIT = f"https://github.com/{REPO}/commit/{SHA}"
MARKER = "<!-- style: reviews/conventions -->"
VIEW = (
    "pr view 11 --json comments --jq [.comments[] | select(.viewerDidAuthor)] | last "
    f'| .body // "" --repo {REPO}'
)
EDIT = f"pr comment 11 --edit-last --create-if-none --body-file - --repo {REPO}"
CREATE = f"pr comment 11 --body-file - --repo {REPO}"


def step(name: str) -> str:
    """The `run:` script of the step `name` of conventions.yml."""
    block = WORKFLOW.split(f"- name: {name}\n", 1)[1]
    lines = block.split("        run: |\n", 1)[1].splitlines()
    script = []
    for line in lines:
        if line.strip() and not line.startswith("          "):
            break
        script.append(line[10:])
    return "\n".join(script) + "\n"


def step_block(name: str) -> str:
    """The whole step `name`, up to the next step."""
    block = WORKFLOW.split(f"- name: {name}\n", 1)[1]
    return block.split("\n      - name: ", 1)[0]


# --- the gate ----------------------------------------------------------------------------


def labeled(labels: tuple[str, ...]) -> bool:
    """`contains(github.event.pull_request.labels.*.name, 'release')` as GitHub evaluates it:
    an element equal to `release`, compared without case."""
    return any(label.lower() == "release" for label in labels)


def gate(
    tmp_path: Path,
    *,
    mode: str = "",
    title: str = "feat: a change",
    labels: tuple[str, ...] = (),
    key: bool = True,
    author: str = "johan",
    actor: str = "johan",
    fork: bool = False,
) -> tuple[int, str, dict[str, str]]:
    """Run the Gate step: the exit code, what it printed and summarized, and its outputs."""
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    summary.write_text("")
    output.write_text("")
    env = {
        "PATH": os.environ["PATH"],
        "HAS_KEY": "true" if key else "false",
        "MODE": mode,
        "TITLE": title,
        "LABELED": "true" if labeled(labels) else "false",
        "AUTHOR": author,
        "ACTOR": actor,
        "HEAD_REPO": "someone/fork" if fork else REPO,
        "REPO": REPO,
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_OUTPUT": str(output),
    }
    done = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step("Gate")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return done.returncode, summary.read_text() + done.stdout + done.stderr, outputs


@pytest.mark.parametrize("mode", ["", "release"])
@pytest.mark.parametrize("title", RELEASE_TITLES)
def test_release_is_the_default_and_reviews_a_release_pr(
    tmp_path: Path, mode: str, title: str
) -> None:
    code, _out, outputs = gate(tmp_path, mode=mode, title=title)
    assert code == 0
    assert outputs == {"mode": "release", "release": "true", "run": "true"}


@pytest.mark.parametrize("mode", ["", "release", "all"])
@pytest.mark.parametrize("title", ["Ship the next version", *OTHER_TITLES])
def test_a_pr_labeled_release_is_a_release_pr_whatever_its_title(
    tmp_path: Path, mode: str, title: str
) -> None:
    code, _out, outputs = gate(tmp_path, mode=mode, title=title, labels=("bug", "release"))
    assert code == 0
    assert outputs == {"mode": mode or "release", "release": "true", "run": "true"}


@pytest.mark.parametrize("title", OTHER_TITLES)
def test_release_passes_any_other_pr_with_a_notice(tmp_path: Path, title: str) -> None:
    code, out, outputs = gate(tmp_path, mode="release", title=title, labels=("bug",))
    assert code == 0
    assert outputs == {"mode": "release", "release": "false", "run": "false"}
    assert "conventions: not a release PR" in out
    assert "labeled `release`" in out
    assert "`<version> Release`" in out
    assert "`release: <version>`" in out
    assert "CONVENTIONS_REVIEW" in out


@pytest.mark.parametrize("title", RELEASE_TITLES + OTHER_TITLES)
def test_the_gate_and_the_script_read_a_title_alike(tmp_path: Path, title: str) -> None:
    _code, _out, outputs = gate(tmp_path, mode="all", title=title)
    assert outputs["release"] == ("true" if fr.is_release_title(title) else "false")


def test_all_reviews_every_pr(tmp_path: Path) -> None:
    for title, release in (("feat: a change", "false"), ("0.7.4 Release", "true")):
        code, _out, outputs = gate(tmp_path, mode="all", title=title)
        assert code == 0
        assert outputs == {"mode": "all", "release": release, "run": "true"}


def test_off_reviews_nothing(tmp_path: Path) -> None:
    for title in ("feat: a change", "release: 0.6.4"):
        code, out, outputs = gate(tmp_path, mode="off", title=title)
        assert code == 0
        assert outputs["run"] == "false"
        assert "conventions: CONVENTIONS_REVIEW is off" in out


def test_another_value_fails_and_names_the_three(tmp_path: Path) -> None:
    code, out, outputs = gate(tmp_path, mode="relase", title="release: 0.6.4")
    assert code == 1
    assert "conventions: CONVENTIONS_REVIEW is `relase`" in out
    for mode in MODES:
        assert f"`{mode}`" in out
    assert "run" not in outputs


def test_a_reviewed_pr_without_the_key_fails_naming_the_secret(tmp_path: Path) -> None:
    code, out, _outputs = gate(tmp_path, mode="release", title="release: 0.6.4", key=False)
    assert code == 1
    assert "conventions: ANTHROPIC_API_KEY is empty; the review cannot run" in out
    # A pull request that no mode reviews needs no key.
    code, _out, outputs = gate(tmp_path, mode="release", title="feat: a change", key=False)
    assert code == 0
    assert outputs["run"] == "false"
    code, _out, outputs = gate(tmp_path, mode="off", title="release: 0.6.4", key=False)
    assert code == 0
    assert outputs["run"] == "false"


def test_a_fork_fails_without_the_key(tmp_path: Path) -> None:
    code, out, _outputs = gate(tmp_path, mode="all", key=False, fork=True)
    assert code == 1
    assert "from a fork gets no secrets" in out


def test_dependabot_passes_and_another_app_fails(tmp_path: Path) -> None:
    bot = "dependabot[bot]"
    code, out, outputs = gate(tmp_path, mode="all", author=bot, actor=bot)
    assert code == 0
    assert outputs["run"] == "false"
    assert "Dependabot PR" in out
    code, out, _outputs = gate(tmp_path, mode="all", author="some-app[bot]")
    assert code == 1
    assert "opened or updated by a GitHub App gets no review" in out
    # A pull request that no mode reviews is not failed for its App either.
    code, _out, outputs = gate(tmp_path, mode="off", author="some-app[bot]")
    assert code == 0
    assert outputs["run"] == "false"
    code, _out, outputs = gate(tmp_path, mode="release", author="some-app[bot]")
    assert code == 0
    assert outputs["run"] == "false"


@pytest.mark.parametrize(
    "case",
    [
        {"mode": "off", "title": "release: 0.6.4"},
        {"mode": "release", "title": "feat: a change"},
        {"mode": "all", "author": "dependabot[bot]", "actor": "dependabot[bot]"},
        {"mode": "all", "author": "some-app[bot]"},
        {"mode": "all", "key": False, "fork": True},
        {"mode": "all", "key": False},
    ],
)
def test_a_run_that_reviews_nothing_posts_no_comment(tmp_path: Path, case: dict) -> None:
    _code, _out, outputs = gate(tmp_path, **case)
    assert outputs.get("run") != "true"
    # The Verdict step, the only one that posts, runs on a reviewed pull request alone: the
    # gate's `run` and, for a README that links no documents, the material's `review`.
    condition = step_block("Verdict").split("\n", 1)[0]
    assert condition.strip().startswith("if: ")
    assert "steps.gate.outputs.run == 'true'" in condition
    assert "steps.prepare.outputs.review == 'true'" in condition


def test_the_gate_reads_the_callers_variable_the_label_and_the_title() -> None:
    block = step_block("Gate").split("run: |", 1)[0]
    assert "MODE: ${{ vars.CONVENTIONS_REVIEW }}" in block
    assert "TITLE: ${{ github.event.pull_request.title }}" in block
    assert "LABELED: ${{ contains(github.event.pull_request.labels.*.name, 'release') }}" in block
    assert "FAMILY_REVIEW_REQUIRED" not in WORKFLOW
    assert "FAMILY_REVIEW_REQUIRED" not in README


# --- the job's own condition -------------------------------------------------------------


def job_condition() -> str:
    """The job's own `if:`, a folded scalar before its steps, joined as YAML folds it."""
    job = WORKFLOW.split("\njobs:\n", 1)[1].split("\n    steps:\n", 1)[0]
    assert job.count("\n    if: >-\n") == 1
    folded = []
    for line in job.split("\n    if: >-\n", 1)[1].splitlines():
        if not line.startswith("      "):
            break
        folded.append(line.strip())
    return " ".join(folded)


def admitted(mode: str, title: str, labels: tuple[str, ...]) -> bool:
    """CONDITION as GitHub evaluates it: `contains`, `startsWith`, `endsWith` and `!=` compare
    strings without case, and an unset variable reads as the empty string."""
    mode, title = mode.lower(), title.lower()
    return (
        labeled(labels)
        or title.startswith("release: ")
        or title.endswith(" release")
        or mode not in ("", "release", "off")
    )


def test_the_job_holds_its_condition() -> None:
    assert job_condition() == CONDITION
    # The job's `if:` reads what a job's condition may: no secret, no step.
    assert "secrets." not in CONDITION
    assert "steps." not in CONDITION


def test_a_pr_labeled_release_gets_the_release_review(tmp_path: Path) -> None:
    """Proof 1 of the plan of .github 0.2.0: a title outside the pattern, the label set."""
    title = "Ship the next version"
    assert not fr.is_release_title(title)
    assert admitted("", title, ("release",))
    code, _out, outputs = gate(tmp_path, title=title, labels=("release",))
    assert code == 0
    assert outputs == {"mode": "release", "release": "true", "run": "true"}


@pytest.mark.parametrize("mode", ["", "release", "off"])
@pytest.mark.parametrize("labels", [(), ("bug",)])
def test_a_pr_without_the_label_and_the_title_skips_the_job(
    mode: str, labels: tuple[str, ...]
) -> None:
    """Proof 1 of the plan of .github 0.2.0: the job does not start, so the check reports as
    skipped."""
    assert not admitted(mode, "feat: a change", labels)


@pytest.mark.parametrize("mode", ["", "release", "off", "all", "relase"])
@pytest.mark.parametrize("labels", [(), ("bug",), ("release",)])
@pytest.mark.parametrize("who", [{}, {"key": False, "fork": True}, {"author": "some-app[bot]"}])
def test_a_skipped_job_hides_no_review_and_no_failure(
    tmp_path: Path, mode: str, labels: tuple[str, ...], who: dict
) -> None:
    """Whatever the condition skips, the Gate would have passed without a review: a mode other
    than `release` and `off` always starts the job, so a wrong value still fails naming the
    three, and a title the condition admits only by its looser reading ends at the Gate."""
    skipped = 0
    for title in ("feat: a change", *RELEASE_TITLES, *OTHER_TITLES):
        code, _out, outputs = gate(tmp_path, mode=mode, title=title, labels=labels, **who)
        if not admitted(mode, title, labels):
            skipped += 1
            assert (code, outputs.get("run")) == (0, "false"), title
    # The condition skips some pull request exactly where no label and no other mode admits it.
    assert bool(skipped) == (mode in ("", "release", "off") and not labeled(labels))


# --- the steps after the gate ------------------------------------------------------------


def test_the_review_and_the_verdict_wait_for_the_documents() -> None:
    prepare = step_block("Prepare the review material")
    assert "id: prepare" in prepare
    assert "MAIN: origin/${{ github.event.repository.default_branch }}" in prepare
    assert "RELEASE: ${{ steps.gate.outputs.release }}" in prepare
    assert '--main "$MAIN"' in prepare
    assert "set -- --release" in prepare
    for name in ("Review", "Verdict"):
        assert "steps.prepare.outputs.review == 'true'" in step_block(name)
    assert "--docs" not in WORKFLOW
    assert "sdk-core" not in WORKFLOW
    assert "fetch-depth: 0" in step_block("Check out the pull request head with full history")


def test_the_readme_describes_the_review_by_mode() -> None:
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/ci.yml`**", 1)[0]
    assert "`CONVENTIONS_REVIEW`" in section
    for mode in MODES:
        assert f"`{mode}`" in section
    assert "`## Documents`" in section
    flat = " ".join(section.split())
    # The release PR by its label and its title, and the job's own condition (.github#47).
    assert "labeled `release`" in flat
    assert "`<version> Release`" in flat
    assert "`release: <version>`" in flat
    assert "coordinate-core 0.7.4" in flat
    assert "`labeled`" in flat
    assert "skipped and passing" in flat
    assert "`pyproject.toml`" in flat
    assert "sdk-core" not in section
    assert "`--docs`" not in README


def test_the_readme_runs_the_review_locally_on_a_release_pr_as_the_workflow() -> None:
    section = README.split("## Running the review locally", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(section.split())
    assert "labeled `release`" in flat
    assert "`<version> Release`" in flat


# --- the verdict -------------------------------------------------------------------------


def verdict_step(
    tmp_path: Path,
    result: dict | None,
    *,
    last_comment: str = "",
    view_fails: bool = False,
    comment_fails: bool = False,
) -> tuple[int, str, list[str], str | None]:
    """Run the Verdict step on ``result``: the exit code, the summary, gh's calls and the
    comment it posted, if any; the step's stdout is left in ``stdout.txt``. ``last_comment``
    is the body of the last comment the token wrote on the pull request, empty when it wrote
    none; ``view_fails`` makes reading it fail, ``comment_fails`` posting the comment."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "last.txt").write_text(last_comment)
    (bin_dir / "calls").unlink(missing_ok=True)
    (bin_dir / "comment.md").unlink(missing_ok=True)
    gh = bin_dir / "gh"
    view = "exit 1" if view_fails else 'cat "$here/last.txt"'
    post = 'cat > "$here/comment.md"'
    if comment_fails:
        post = "echo 'HTTP 403: Resource not accessible by integration (ghs_abc123)' >&2; exit 1"
    gh.write_text(
        "#!/bin/sh\n"
        'here=$(dirname "$0")\n'
        'printf "%s\\n" "$*" >> "$here/calls"\n'
        'case "$1 $2" in\n'
        f'  "pr view") {view} ;;\n'
        f'  "pr comment") {post} ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n"
    )
    gh.chmod(0o755)
    result_file = tmp_path / "verdict.json"
    result_file.unlink(missing_ok=True)
    if result is not None:
        result_file.write_text(json.dumps(result))
    summary = tmp_path / "summary.md"
    summary.write_text("")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "RESULT_FILE": str(result_file),
        "GH_TOKEN": "dummy",
        "REPO": REPO,
        "PR": "11",
        "HEAD_SHA": SHA,
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    done = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step("Verdict")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (tmp_path / "stdout.txt").write_text(done.stdout)
    calls = (bin_dir / "calls").read_text().splitlines() if (bin_dir / "calls").exists() else []
    comment = (bin_dir / "comment.md").read_text() if (bin_dir / "comment.md").exists() else None
    return done.returncode, summary.read_text() + done.stderr, calls, comment


def result(verdict: str, findings: list[dict], *, release: bool = False) -> dict:
    return {
        "verdict": verdict,
        "findings": findings,
        "range": {"release": release, "since": "a" * 40, "tag": "v0.6.3" if release else None},
        "documents": ["sdk-core: docs/conventions.md", "sdk-usda-psd: docs/conventions.md"],
        "summary": "conventions: verdict=…",
    }


def finding(document: str, text: str, file: str = "src/pkg/mod.py", line=2, blocking=False):
    return {"document": document, "file": file, "line": line, "blocking": blocking, "text": text}


def test_a_blocked_verdict_fails_and_posts_the_findings_in_the_style(tmp_path: Path) -> None:
    findings = [
        finding(
            "sdk-core: docs/conventions.md#tests", "The test commit is missing.", blocking=True
        ),
        finding("", "The body has no `## Decisions taken`.", file="", line=None),
        finding("", "A stray print.", file="src/pkg/cli.py", line=7),
    ]
    code, summary, calls, comment = verdict_step(
        tmp_path, result("not ready", findings, release=True)
    )
    assert code == 1
    expected = (
        f"{MARKER}\n"
        f"**Blocked.** 3 findings, 1 blocking, at {COMMIT}.\n\n"
        "Judged: the release's range from `v0.6.3` to the head, against 2 documents of "
        "`README.md` on `main`.\n\n"
        "1. **sdk-core: docs/conventions.md#tests** The test commit is missing. "
        "`src/pkg/mod.py:2`. Blocks: yes.\n"
        "2. **the pull request** The body has no `## Decisions taken`. Blocks: no.\n"
        "3. **`src/pkg/cli.py:7`** A stray print. Blocks: no.\n"
    )
    assert summary == expected
    assert comment == expected
    assert calls[-1].startswith("pr comment 11 --edit-last --create-if-none --body-file -")


def test_an_approval_without_findings_passes_and_creates_the_comment(tmp_path: Path) -> None:
    code, summary, calls, comment = verdict_step(tmp_path, result("ready", []))
    assert code == 0
    assert summary == (
        f"{MARKER}\n**Approved.** No findings at {COMMIT}.\n\n"
        "Judged: the pull request's own diff, against 2 documents of `README.md` on `main`.\n"
    )
    assert comment == summary
    assert calls == [VIEW, EDIT]


def test_findings_that_do_not_block_create_the_comment_when_there_is_none(
    tmp_path: Path,
) -> None:
    # The release PR coordinate-core#441: `ready` with six findings, and no comment before.
    findings = [
        finding("coordinate-core: docs/style/pulls.md#pr", "A bullet names no file."),
        finding("", "The body cites a commit by a short hash.", file="", line=None),
    ]
    code, summary, calls, comment = verdict_step(tmp_path, result("ready", findings, release=True))
    assert code == 0
    assert summary.startswith(
        f"{MARKER}\n**Findings.** 2 findings, none blocking, at {COMMIT}.\n\n"
        "Judged: the release's range from `v0.6.3` to the head"
    )
    assert comment == summary
    assert calls == [VIEW, EDIT]


def test_an_approval_edits_the_earlier_comment_in_place(tmp_path: Path) -> None:
    earlier = f"{MARKER}\n**Blocked.** 1 finding, 1 blocking, at {COMMIT}.\n"
    code, summary, calls, comment = verdict_step(
        tmp_path, result("ready", []), last_comment=earlier
    )
    assert code == 0
    assert summary.startswith(f"{MARKER}\n**Approved.** No findings at {COMMIT}.\n")
    assert comment == summary
    assert calls == [VIEW, EDIT]


@pytest.mark.parametrize("verdict", ["ready", "not ready"])
def test_another_workflows_comment_is_never_overwritten(tmp_path: Path, verdict: str) -> None:
    findings = [] if verdict == "ready" else [finding("", "A stray print.", blocking=True)]
    code, summary, calls, comment = verdict_step(
        tmp_path, result(verdict, findings), last_comment="<!-- another workflow -->\nhello\n"
    )
    assert code == (0 if verdict == "ready" else 1)
    assert comment == summary
    assert calls == [VIEW, CREATE]


@pytest.mark.parametrize("verdict", ["ready", "not ready"])
def test_unread_comments_get_a_new_comment(tmp_path: Path, verdict: str) -> None:
    # When the token's comments cannot be read, `--edit-last` could edit another workflow's.
    findings = [] if verdict == "ready" else [finding("", "A stray print.", blocking=True)]
    code, summary, calls, comment = verdict_step(
        tmp_path, result(verdict, findings), view_fails=True
    )
    assert code == (0 if verdict == "ready" else 1)
    assert comment == summary
    assert calls == [VIEW, CREATE]


def test_findings_that_do_not_block_pass_and_update_an_earlier_comment(tmp_path: Path) -> None:
    findings = [
        finding("sdk-core: docs/conventions.md#names", "A name departs from the convention.")
    ]
    earlier = f"{MARKER}\n**Blocked.** 1 finding, 1 blocking, at {COMMIT}.\n"
    code, summary, calls, comment = verdict_step(
        tmp_path, result("ready", findings), last_comment=earlier
    )
    assert code == 0
    assert summary.startswith(f"{MARKER}\n**Findings.** 1 finding, none blocking, at {COMMIT}.\n")
    assert comment == summary
    assert calls == [VIEW, EDIT]
    # The comment of the earlier form is the review's too.
    old = "<!-- conventions -->\n## conventions: `not ready`\n"
    _code, _summary, calls, comment = verdict_step(
        tmp_path, result("ready", findings), last_comment=old
    )
    assert comment is not None
    assert calls == [VIEW, EDIT]


@pytest.mark.parametrize("verdict", ["ready", "not ready"])
def test_a_failed_post_is_in_the_summary_and_a_warning(tmp_path: Path, verdict: str) -> None:
    # The verdict still decides the check, and the run says why the PR has no comment.
    findings = [] if verdict == "ready" else [finding("", "A stray print.", blocking=True)]
    code, summary, calls, comment = verdict_step(
        tmp_path, result(verdict, findings), comment_fails=True
    )
    assert code == (0 if verdict == "ready" else 1)
    assert comment is None
    assert calls == [VIEW, EDIT]
    line = (
        "conventions: posting the PR comment failed: HTTP 403: Resource not accessible by "
        "integration ([redacted])"
    )
    assert summary.endswith(f"\n{line}\n")
    assert f"::warning::{line}\n" in (tmp_path / "stdout.txt").read_text()
    assert "ghs_abc123" not in summary + (tmp_path / "stdout.txt").read_text()


def test_no_verdict_fails_with_the_scripts_line(tmp_path: Path) -> None:
    code, summary, calls, comment = verdict_step(
        tmp_path,
        {"verdict": None, "summary": "conventions: no verdict (the turn cap of 120 was reached)"},
    )
    assert code == 1
    assert summary.startswith("## conventions: no verdict\n\nconventions: no verdict (the turn cap")
    assert comment is None
    assert calls == []
    code, summary, _calls, _comment = verdict_step(tmp_path, None)
    assert code == 1
    assert "the review wrote no result" in summary
