"""The conventions review runs by mode on any repository's documents (C57 as amended by
coordinate-core#364, .github#32). The job's own `if:` skips a pull request that is no release's
and that no other mode could review, so the caller's check reports as skipped and passing
(.github#47), and any event of the caller that is not a pull request's opening, push, reopening
or edit, so a caller that also runs on a push to `main` or on a dispatch changes nothing for it
(step 1 of .github 0.5.0). The step `Gate` of conventions.yml then decides from the caller's
`WORKFLOW_CONVENTIONS_MODE` variable, `release` or `all` (step 1.1 of .github 0.5.0), the pull
request's label `release` and its title whether the review runs, before any checkout or API
call; the step `Verdict` writes the check's comment in
the style of docs/style/reviews.md on every run that reviewed the pull request, `ready` included
(.github#36). Both steps call the script, `gate` and `verdict`, from its checkout in `.sdk-gates`
(step 2 of .github 0.5.0). The tests run the steps' own scripts, as the workflow holds them, in
the environment the runner gives a step, and evaluate the job's own condition as the file holds it
with `expressions.py`. A release PR is told by its label `release` or by its title
`<version> Release` alone, and the older title form is no release PR's (step 2.1 of
.github 0.5.0). Where the Gate lets a review run, the job waits 60 seconds before it checks the
head out and prepares its material, so a push or an edit within that minute cancels the run
before it made a model call (step 6.2 of .github 0.5.0, .github#147)."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import conventions as fr
import pytest
from expressions import holds

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "conventions.py"
WORKFLOW = (ROOT / ".github" / "workflows" / "conventions.yml").read_text()
README = (ROOT / "README.md").read_text()
MODES = ("release", "all")
# Values of the mode that the Gate refuses: `off` among them, since the switch WORKFLOW_CONVENTIONS
# of the trigger file replaces it (step 1.1 of .github 0.5.0).
WRONG_MODES = ["relase", "off", "Off", "OFF", "on", "none"]
# A release PR's title, `<version> Release` (docs/style/pulls.md#release-pr of a coordinate root).
RELEASE_TITLES = ["0.7.4 Release"]
# The title form that a release PR carried until every workspace had adopted coordinate-core 0.7.4,
# retired in step 2.1 of .github 0.5.0: no release PR's title any more.
OLD_TITLES = ["release: 0.6.4", "release: 0.6.4-rc.1", "release: v0.6.4"]
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
    *OLD_TITLES,
]
# The types of a pull request's event that the review runs on: its opening, a push, its reopening
# and an edit (step 1 of .github 0.5.0).
FOUR = ["opened", "synchronize", "reopened", "edited"]
# The job's own condition (.github#47), its folded lines joined as YAML folds them: the caller's
# event first, then the release PR or the mode as before.
CONDITION = (
    "github.event_name == 'pull_request' "
    f"&& contains(fromJSON('{json.dumps(FOUR)}'), github.event.action) "
    "&& (contains(github.event.pull_request.labels.*.name, 'release') "
    "|| endsWith(github.event.pull_request.title, ' Release') "
    "|| (vars.WORKFLOW_CONVENTIONS_MODE != '' "
    "&& vars.WORKFLOW_CONVENTIONS_MODE != 'release'))"
)
# The events of a caller that the condition skips, each with its action: a push to `main`, a
# dispatch, the other types of a pull request's event and the events that are no pull request's.
OTHER_EVENTS = [
    ("push", ""),
    ("workflow_dispatch", ""),
    ("schedule", ""),
    ("pull_request", "closed"),
    ("pull_request", "labeled"),
    ("pull_request", "unlabeled"),
    ("pull_request", "assigned"),
    ("pull_request", "ready_for_review"),
    ("pull_request", "converted_to_draft"),
    ("pull_request", "review_requested"),
    ("pull_request_target", "opened"),
    ("merge_group", "checks_requested"),
    ("issue_comment", "created"),
]
# The expression functions that the condition may call: actionlint knows them all.
FUNCTIONS = {"contains", "endsWith", "fromJSON"}
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
# A stub `gh` that logs its calls and answers none: the Gate makes no call.
GH_LOG = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$(dirname "$0")/calls"\nexit 1\n'


def step(name: str) -> str:
    """The `run:` script of the step `name` of conventions.yml: a block scalar or one line."""
    run = ("\n" + step_block(name)).split("\n        run: ", 1)[1]
    if not run.startswith("|\n"):
        return run.split("\n", 1)[0] + "\n"
    script = []
    for line in run[2:].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        script.append(line[10:])
    return "\n".join(script) + "\n"


def step_block(name: str) -> str:
    """The whole step `name`, up to the next step."""
    block = WORKFLOW.split(f"- name: {name}\n", 1)[1]
    return block.split("\n      - name: ", 1)[0]


def job_env(tmp_path: Path, gh: str) -> dict[str, str]:
    """The environment a step of the job runs in, as the runner gives it: the workspace with the
    script's checkout in `.sdk-gates`, the runner's temporary directory, the files of the step's
    outputs and summary, emptied, and the stub `gh` first on the path."""
    workspace = tmp_path / "workspace"
    script = workspace / ".sdk-gates" / "scripts" / "conventions.py"
    if not script.exists():
        script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, script)
    temp = tmp_path / "temp"
    temp.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "calls").unlink(missing_ok=True)
    (bin_dir / "gh").write_text(gh)
    (bin_dir / "gh").chmod(0o755)
    (tmp_path / "summary.md").write_text("")
    (tmp_path / "output.txt").write_text("")
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(temp),
        "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }


def run_step(name: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the `run:` script of the step `name` as the runner's default shell runs it, in the
    workspace."""
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step(name)],
        env=env,
        cwd=env["GITHUB_WORKSPACE"],
        capture_output=True,
        text=True,
        check=False,
    )


def gh_calls(tmp_path: Path) -> list[str]:
    """The calls the stub `gh` logged."""
    calls = tmp_path / "bin" / "calls"
    return calls.read_text().splitlines() if calls.exists() else []


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
    author: str = "opener",
    actor: str = "opener",
    fork: bool = False,
    read_token_unused: bool = False,
) -> tuple[int, str, dict[str, str]]:
    """Run the Gate step: the exit code, what it printed and summarized, and its outputs.

    ``read_token_unused``: a public caller passed DOCUMENTS_READ_TOKEN, which its check does
    not use (.github#83). The Gate makes no call of `gh`."""
    done = run_step(
        "Gate",
        gate_env(
            tmp_path,
            mode=mode,
            title=title,
            labels=labels,
            key=key,
            author=author,
            actor=actor,
            fork=fork,
            read_token_unused=read_token_unused,
        ),
    )
    assert gh_calls(tmp_path) == []
    output = (tmp_path / "output.txt").read_text()
    outputs = dict(line.split("=", 1) for line in output.splitlines())
    summary = (tmp_path / "summary.md").read_text()
    return done.returncode, summary + done.stdout + done.stderr, outputs


def gate_env(
    tmp_path: Path,
    *,
    mode: str = "",
    title: str = "feat: a change",
    labels: tuple[str, ...] = (),
    key: bool = True,
    author: str = "opener",
    actor: str = "opener",
    fork: bool = False,
    read_token_unused: bool = False,
) -> dict[str, str]:
    """The environment of the Gate step: the job's, and the values its `env:` block gives."""
    return {
        **job_env(tmp_path, GH_LOG),
        "HAS_KEY": "true" if key else "false",
        "MODE": mode,
        "TITLE": title,
        "LABELED": "true" if labeled(labels) else "false",
        "AUTHOR": author,
        "ACTOR": actor,
        "HEAD_REPO": "someone/fork" if fork else REPO,
        "REPO": REPO,
        "READ_TOKEN_UNUSED": "true" if read_token_unused else "false",
    }


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
    assert "`release: <version>`" not in out
    assert "with WORKFLOW_CONVENTIONS_MODE release the review runs" in out
    # The notice names the one title form.
    assert (
        "conventions: not a release PR; with WORKFLOW_CONVENTIONS_MODE release the review runs on "
        "a PR labeled `release` or titled `<version> Release`\n" in out
    )


@pytest.mark.parametrize("title", RELEASE_TITLES + OTHER_TITLES)
def test_the_gate_and_the_script_read_a_title_alike(tmp_path: Path, title: str) -> None:
    _code, _out, outputs = gate(tmp_path, mode="all", title=title)
    assert outputs["release"] == ("true" if fr.is_release_title(title) else "false")


# The pattern of a release PR's title that the Gate matched with `grep -E` until step 2 of
# .github 0.5.0, when the script's `is_release_title` took its place, without the alternative of the
# older form, which step 2.1 retired.
GATE_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+ Release$"


@pytest.mark.parametrize("title", ["feat: a change", "Ship the next version", *RELEASE_TITLES])
@pytest.mark.parametrize("more", [False, True])
def test_the_script_reads_a_title_as_the_gates_grep_did(title: str, more: bool) -> None:
    """The rule that tells a release PR by its title stands once, in the script, and gives the
    Gate's answers of before for the titles these tests use, but for the older form."""
    titles = OTHER_TITLES if more else [title]
    for each in titles:
        done = subprocess.run(
            ["grep", "-Eq", GATE_PATTERN], input=f"{each}\n", text=True, check=False
        )
        assert done.returncode in (0, 1)
        assert fr.is_release_title(each) == (done.returncode == 0), each


def test_the_gate_and_the_verdict_each_call_the_script_once() -> None:
    """The Gate and the Verdict are one call each of the script from its checkout, on the
    runner's `python3` with `-I`, before and without uv; neither holds a pattern of a title."""
    for name, command in (("Gate", "gate"), ("Verdict", "verdict")):
        call = f'python3 -I "$GITHUB_WORKSPACE/.sdk-gates/scripts/conventions.py" {command}\n'
        assert step(name) == call
        assert "uv " not in step_block(name)
    assert "grep -E" not in WORKFLOW


def test_the_workflow_holds_no_inline_code() -> None:
    """No `run:` feeds Python a here-document or a `-c` program: the code is the script's."""
    assert "<<" not in WORKFLOW
    assert re.search(r"python3?( -[A-Za-z]+)* -( |$)", WORKFLOW, re.M) is None
    assert re.search(r"python3?( -[A-Za-z]+)* -c\b", WORKFLOW) is None


# The Python of the job's steps, where neither the SDK nor its HTTP client can be imported: the
# program runs the script as `python3 -I <script> <command>` does.
WITHOUT_SDK = (
    "import runpy, sys\n"
    "sys.modules['anthropic'] = None\n"
    "sys.modules['httpx2'] = None\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def test_the_gate_and_the_verdict_run_where_the_sdk_cannot_be_imported(tmp_path: Path) -> None:
    """The runner's `python3` has no `anthropic`: the script imports it where the review needs
    it, so `gate` and `verdict` load on the standard library alone."""
    blocked = subprocess.run(
        [sys.executable, "-I", "-c", WITHOUT_SDK.split("sys.argv")[0] + "import anthropic\n"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 1
    assert "ModuleNotFoundError" in blocked.stderr
    env = gate_env(tmp_path, mode="all")
    script = f"{env['GITHUB_WORKSPACE']}/.sdk-gates/scripts/conventions.py"
    done = subprocess.run(
        [sys.executable, "-I", "-c", WITHOUT_SDK, script, "gate"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stderr) == (0, "")
    assert (tmp_path / "output.txt").read_text() == "mode=all\nrelease=false\nrun=true\n"
    env = verdict_env(tmp_path, result("ready", []))
    done = subprocess.run(
        [sys.executable, "-I", "-c", WITHOUT_SDK, script, "verdict"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stderr) == (0, "")
    assert (tmp_path / "bin" / "comment.md").read_text().startswith(f"{MARKER}\n**Approved.**")


def test_all_reviews_every_pr(tmp_path: Path) -> None:
    for title, release in (("feat: a change", "false"), ("0.7.4 Release", "true")):
        code, _out, outputs = gate(tmp_path, mode="all", title=title)
        assert code == 0
        assert outputs == {"mode": "all", "release": release, "run": "true"}


@pytest.mark.parametrize("value", WRONG_MODES)
@pytest.mark.parametrize("title", ["feat: a change", "0.7.4 Release"])
def test_another_value_off_included_fails_and_names_the_two(
    tmp_path: Path, value: str, title: str
) -> None:
    """The mode has two values; `off` is a wrong one like any other, which fails before the
    key, the App and Dependabot are looked at."""
    for who in ({}, {"key": False}, {"author": "some-app[bot]"}):
        code, out, outputs = gate(tmp_path, mode=value, title=title, **who)
        assert code == 1
        assert (
            f"conventions: WORKFLOW_CONVENTIONS_MODE is `{value}`; it is `release` or `all` (C57)"
            in out
        )
        assert "switched off" not in out
        assert outputs == {}


@pytest.mark.parametrize(
    ("value", "mode"),
    [("Release", "release"), ("RELEASE", "release"), ("All", "all"), ("ALL", "all")],
)
@pytest.mark.parametrize("title", ["feat: a change", "0.7.4 Release"])
def test_the_gate_reads_the_mode_without_case_as_the_condition_does(
    tmp_path: Path, value: str, mode: str, title: str
) -> None:
    """The condition compares the mode without case (finding 1 of the review of .github#60), so
    the Gate reads `All` as `all`: one value means one mode in both."""
    code, _out, outputs = gate(tmp_path, mode=value, title=title)
    expected, _out, _outputs = gate(tmp_path, mode=mode, title=title)
    assert code == expected == 0
    assert outputs == _outputs
    assert outputs["mode"] == mode


def test_a_reviewed_pr_without_the_key_fails_naming_the_secret(tmp_path: Path) -> None:
    code, out, _outputs = gate(tmp_path, mode="release", title="0.7.4 Release", key=False)
    assert code == 1
    assert "conventions: ANTHROPIC_API_KEY is empty; the review cannot run" in out
    # A pull request that no mode reviews needs no key.
    code, _out, outputs = gate(tmp_path, mode="release", title="feat: a change", key=False)
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
    code, _out, outputs = gate(tmp_path, mode="release", author="some-app[bot]")
    assert code == 0
    assert outputs["run"] == "false"


@pytest.mark.parametrize(
    "case",
    [
        {"mode": "off", "title": "0.7.4 Release"},
        {"mode": "relase", "title": "0.7.4 Release"},
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
    assert "MODE: ${{ vars.WORKFLOW_CONVENTIONS_MODE }}" in block
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


def kept_types() -> list[str]:
    """The types of a pull request's event that the job's condition keeps, read from its own
    `fromJSON` list."""
    match = re.search(r"fromJSON\('(\[[^']*\])'\), github\.event\.action\)", job_condition())
    assert match, job_condition()
    return json.loads(match.group(1))


def admitted(
    mode: str,
    title: str,
    labels: tuple[str, ...],
    *,
    event: str = "pull_request",
    action: str = "opened",
) -> bool:
    """The job's own condition, as the file holds it, evaluated by `expressions.py` as GitHub
    evaluates it: strings compare without case, and an unset variable reads as the empty string.
    A called workflow reads its caller's `github.event_name` and `github.event.action`."""
    pull_request = {"title": title, "labels": [{"name": label} for label in labels]}
    context = {
        "github": {
            "event_name": event,
            "event": {"action": action, "pull_request": pull_request},
        },
        "vars": {"WORKFLOW_CONVENTIONS_MODE": mode} if mode else {},
    }
    return holds(job_condition(), context)


def test_the_job_holds_its_condition() -> None:
    assert job_condition() == CONDITION
    # The job's `if:` reads what a job's condition may: no secret, no step.
    assert "secrets." not in CONDITION
    assert "steps." not in CONDITION


def test_the_condition_calls_only_the_functions_actionlint_knows() -> None:
    assert set(re.findall(r"([A-Za-z]+)\(", job_condition())) == FUNCTIONS


@pytest.mark.parametrize("action", FOUR)
@pytest.mark.parametrize("title", RELEASE_TITLES)
def test_the_job_runs_on_the_four_types_of_a_pull_request(action: str, title: str) -> None:
    """A caller of today runs on exactly these four, so it sees no change."""
    assert kept_types() == FOUR
    assert admitted("", title, (), action=action)
    assert admitted("all", "feat: a change", (), action=action)


@pytest.mark.parametrize(("event", "action"), OTHER_EVENTS)
@pytest.mark.parametrize("mode", ["", "release", "all", "ALL", "off", "relase"])
@pytest.mark.parametrize("labels", [(), ("release",)])
def test_the_job_skips_every_other_event_of_its_caller(
    event: str, action: str, mode: str, labels: tuple[str, ...]
) -> None:
    """A caller that also runs on a push to `main` or on a dispatch starts no review there, and
    its check reports as skipped, whatever the mode, the title and the label."""
    for title in ("feat: a change", *RELEASE_TITLES):
        assert not admitted(mode, title, labels, event=event, action=action), title


def test_a_pr_labeled_release_gets_the_release_review(tmp_path: Path) -> None:
    """Proof 1 of the plan of .github 0.2.0: a title outside the pattern, the label set."""
    title = "Ship the next version"
    assert not fr.is_release_title(title)
    assert admitted("", title, ("release",))
    code, _out, outputs = gate(tmp_path, title=title, labels=("release",))
    assert code == 0
    assert outputs == {"mode": "release", "release": "true", "run": "true"}


@pytest.mark.parametrize("title", OLD_TITLES)
def test_the_older_title_form_is_no_release_pr(tmp_path: Path, title: str) -> None:
    """In the mode `release` the job's condition skips a pull request with that title and no
    label, as it skips any other, and the Gate and the script read it as no release PR's; the
    label still makes it one (step 2.1 of .github 0.5.0)."""
    assert fr.release_version(title) is None
    assert not fr.is_release_title(title)
    for mode in ("", "release", "Release"):
        assert not admitted(mode, title, ()), mode
    assert admitted("", title, ("release",))
    code, out, outputs = gate(tmp_path, mode="all", title=title)
    assert (code, outputs) == (0, {"mode": "all", "release": "false", "run": "true"})
    code, out, outputs = gate(tmp_path, mode="release", title=title)
    assert (code, outputs) == (0, {"mode": "release", "release": "false", "run": "false"})
    assert "conventions: not a release PR" in out
    code, _out, outputs = gate(tmp_path, mode="release", title=title, labels=("release",))
    assert (code, outputs) == (0, {"mode": "release", "release": "true", "run": "true"})


# The edges of the title rule, held as `is_release_title` reads them since step 2 of .github
# 0.5.0 (the decisions on .github#123): the whole title, stripped of white space at its ends, with
# Python's digits.


@pytest.mark.parametrize("title", ["x\n0.7.4 Release", "0.7.4 Release\nx", "0.7.4\nRelease"])
def test_a_title_of_several_lines_is_no_release_title(tmp_path: Path, title: str) -> None:
    """The Gate's `grep -E` matched each line alone; the script matches the whole title, so a
    title whose last line alone is a release's is none, though the condition admits it by its
    end."""
    assert fr.release_version(title) is None
    assert not fr.is_release_title(title)
    _code, _out, outputs = gate(tmp_path, mode="all", title=title)
    assert outputs["release"] == "false"


@pytest.mark.parametrize(
    "title",
    [" 0.7.4 Release", "0.7.4 Release ", "\t0.7.4 Release", "0.7.4 Release\t", "0.7.4 Release\n"],
)
def test_a_title_with_white_space_at_an_end_is_a_release_title(tmp_path: Path, title: str) -> None:
    assert fr.release_version(title) == "0.7.4"
    assert fr.is_release_title(title)
    _code, _out, outputs = gate(tmp_path, mode="all", title=title)
    assert outputs["release"] == "true"


@pytest.mark.parametrize(
    ("title", "version"),
    [
        ("\u0660.\u0667.\u0664 Release", "\u0660.\u0667.\u0664"),
        ("\uff10.\uff17.\uff14 Release", "\uff10.\uff17.\uff14"),
    ],
)
def test_a_title_whose_digits_are_not_ascii_is_a_release_title(
    tmp_path: Path, title: str, version: str
) -> None:
    """Python's `\\d` matches any decimal digit, so Arabic-Indic and full-width digits make a
    release title, and the version is named in them."""
    assert fr.release_version(title) == version
    assert fr.is_release_title(title)
    _code, _out, outputs = gate(tmp_path, mode="all", title=title)
    assert outputs["release"] == "true"


@pytest.mark.parametrize("mode", ["", "release", "Release"])
@pytest.mark.parametrize("labels", [(), ("bug",)])
def test_a_pr_without_the_label_and_the_title_skips_the_job(
    mode: str, labels: tuple[str, ...]
) -> None:
    """Proof 1 of the plan of .github 0.2.0: the job does not start, so the check reports as
    skipped."""
    assert not admitted(mode, "feat: a change", labels)


@pytest.mark.parametrize("mode", ["all", "ALL", *WRONG_MODES])
@pytest.mark.parametrize("labels", [(), ("bug",)])
def test_a_mode_but_release_starts_the_job_off_included(mode: str, labels: tuple[str, ...]) -> None:
    """`all` reviews every pull request, and a wrong value, `off` among them, reaches the Gate,
    which fails naming the two (step 1.1 of .github 0.5.0)."""
    assert admitted(mode, "feat: a change", labels)


@pytest.mark.parametrize(
    "mode", ["", "release", "off", "all", "relase", "Off", "OFF", "Release", "ALL"]
)
@pytest.mark.parametrize("labels", [(), ("bug",), ("release",)])
@pytest.mark.parametrize("who", [{}, {"key": False, "fork": True}, {"author": "some-app[bot]"}])
def test_a_skipped_job_hides_no_review_and_no_failure(
    tmp_path: Path, mode: str, labels: tuple[str, ...], who: dict
) -> None:
    """Whatever the condition skips, the Gate would have passed without a review: a mode other
    than `release`, in any case, always starts the job, so a wrong value, `off` among them, still
    fails naming the two; a value that differs from `release` by case alone is that mode in the
    Gate too; and a title the condition admits only by its looser reading ends at the Gate. The
    Gate runs where the condition skips the job, the pull requests this test holds it to."""
    skipped = 0
    for title in ("feat: a change", *RELEASE_TITLES, *OTHER_TITLES):
        if not admitted(mode, title, labels):
            skipped += 1
            code, _out, outputs = gate(tmp_path, mode=mode, title=title, labels=labels, **who)
            assert (code, outputs.get("run")) == (0, "false"), title
    # The condition skips some pull request exactly where no label and no other mode admits it.
    assert bool(skipped) == (mode.lower() in ("", "release") and not labeled(labels))


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


def job_steps() -> list[tuple[str, str]]:
    """The job's steps in order, each its name and its block up to the next step."""
    steps = WORKFLOW.split("\n    steps:\n", 1)[1]
    blocks = re.split(r"^      - name: ", steps, flags=re.M)[1:]
    return [(block.split("\n", 1)[0], block) for block in blocks]


def condition_of(block: str) -> str | None:
    """The `if:` of a step, or None where it has none."""
    found = re.search(r"^        if: (.*)$", block, re.M)
    return found.group(1) if found else None


def checkout_of(block: str) -> list[str]:
    """What a checkout step runs: its `uses:` line and its `with:` lines."""
    lines = block.split("\n        uses: ", 1)[1].splitlines()
    kept = [lines[0]]
    if len(lines) > 1 and lines[1] == "        with:":
        kept += [line.strip() for line in lines[2:] if line.startswith("          ")]
    return kept


SCRIPT_STEP = "Check out the review script from xippios/.github"
HEAD_STEP = "Check out the pull request head with full history"
WAIT_STEP = "Wait 60 seconds before reading the pull request"
GATE_CHECKOUT = "Check out the script for the gate from xippios/.github"


def test_the_script_is_checked_out_before_the_gate_with_no_condition() -> None:
    """The Gate calls the script, so a first step checks it out, as the checkout after the
    head's does, into a workspace that holds nothing of the pull request yet (step 2 of
    .github 0.5.0)."""
    (first, block), (second, _gate) = job_steps()[:2]
    assert second == "Gate"
    assert first.startswith("Check out")
    assert condition_of(block) is None
    assert checkout_of(block) == checkout_of(step_block(SCRIPT_STEP))
    for setting in (
        "repository: xippios/.github",
        "ref: ${{ job.workflow_sha }}",
        "path: .sdk-gates",
        "persist-credentials: false",
    ):
        assert setting in checkout_of(block)


def test_everything_after_the_gate_waits_for_its_output() -> None:
    """A pull request that the Gate turns away costs one checkout of the script, and no
    checkout of the head, no key and no model call. The head's checkout empties the workspace,
    so the script is checked out again after it, where Prepare's check of a link reads it."""
    names = [name for name, _block in job_steps()]
    assert names[2:6] == [WAIT_STEP, HEAD_STEP, SCRIPT_STEP, "Install uv"]
    assert names[-3:] == ["Prepare the review material", "Review", "Verdict"]
    for name, block in job_steps()[2:]:
        assert "steps.gate.outputs.run == 'true'" in str(condition_of(block)), name


# --- the wait (step 6.2 of .github 0.5.0, .github#147) -----------------------------------


def test_the_wait_stands_after_the_gate_and_before_the_head_and_the_material() -> None:
    """No step but the Gate's own comes before it, the script's checkout and the Gate, and the
    run that judges checks the head out and prepares its material after it, so it reads the pull
    request as it stands a minute after the Gate."""
    names = [name for name, _block in job_steps()]
    assert names[:3] == [GATE_CHECKOUT, "Gate", WAIT_STEP]
    assert names.count(WAIT_STEP) == 1
    wait = names.index(WAIT_STEP)
    assert wait < names.index(HEAD_STEP) < names.index("Prepare the review material")
    assert wait < names.index("Review")


def test_the_wait_carries_the_gates_condition_and_a_skipped_run_does_not_wait() -> None:
    """The wait carries the condition of the steps after the Gate, so a run that the Gate turns
    away ends without it, and a run that it lets through waits."""
    condition = condition_of(step_block(WAIT_STEP))
    assert condition == "steps.gate.outputs.run == 'true'"
    assert condition == condition_of(step_block(HEAD_STEP))
    for run, waits in (("true", True), ("false", False), ("", False)):
        assert holds(condition, {"steps": {"gate": {"outputs": {"run": run}}}}) is waits, run


def test_the_wait_sleeps_60_seconds_fixed_and_nothing_else() -> None:
    """A fixed minute after the Gate, not measured from the event: the step is its name, its
    condition and one call of `sleep`, with no id, no environment and no time read. The job's
    concurrency group of the pull request cancels the waiting run on a newer push or edit."""
    block = step_block(WAIT_STEP)
    keys = [line.strip().split(":", 1)[0] for line in block.splitlines() if line.strip()]
    assert keys == ["if", "run"]
    assert step(WAIT_STEP) == "sleep 60\n"
    assert WORKFLOW.count("sleep") == 1
    group = "conventions-${{ github.repository }}-${{ github.event.pull_request.number }}"
    assert f"    concurrency:\n      group: {group}\n      cancel-in-progress: true\n" in WORKFLOW


def test_the_readme_says_the_wait_where_and_why() -> None:
    """The entry of conventions.yml says the wait in two plain sentences: what it is, where it
    stands, that a skipped run and a run on a range do not wait, and why."""
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("\n  - **The events**", 1)[0]
    flat = " ".join(section.split())
    assert (
        "Where the Gate lets a review run, the step after it waits 60 seconds before the head is "
        "checked out and the material prepared" in flat
    )
    assert "a run that the Gate skips does not wait" in flat
    assert "neither does a run on a range, since no edit follows the merge it judges" in flat
    assert "cancels the run before it made a model call" in flat
    assert "the run that judges reads the pull request as it then stands" in flat
    assert "(https://github.com/xippios/.github/issues/147)" in flat
    # The timeout's sentence stays true with a minute less.
    assert "The job times out after 45 minutes" in flat


def test_the_readme_names_the_gate_and_the_verdict_of_the_script() -> None:
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/conventions-range.yml`**", 1)[0]
    flat = " ".join(section.split())
    assert "`conventions.py gate`" in flat
    assert "`conventions.py verdict`" in flat


def test_the_readme_describes_the_review_by_mode() -> None:
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/ci.yml`**", 1)[0]
    assert "`WORKFLOW_CONVENTIONS_MODE`" in section
    for mode in MODES:
        assert f"`{mode}`" in section
    assert "`## Documents`" in section
    flat = " ".join(section.split())
    # The mode's two values, and `off` a wrong one (step 1.1 of .github 0.5.0).
    mode = flat.split("**The mode**:", 1)[1].split(" - **", 1)[0]
    assert "the caller's variable `WORKFLOW_CONVENTIONS_MODE`" in mode
    assert "`release`, the default when neither is set, reviews a release pull request" in mode
    assert "`all` reviews every pull request" in mode
    assert "Any other value, `off` among them, fails the check and names the two" in mode
    assert "reviews none" not in mode
    assert "names the three" not in flat
    # The release PR by its label and its title, and the job's own condition (.github#47).
    assert "labeled `release`" in flat
    assert "`<version> Release`" in flat
    assert "`release: <version>`" not in flat
    assert "coordinate-core 0.7.4" not in flat
    assert "admits a title by its end, a space and `Release`, and the Gate below matches it" in flat
    assert "by its start" not in flat
    # A caller runs on no label, so a label set later counts from the next event (.github#68).
    assert "`labeled`" not in flat
    assert "a label set after the opening counts from the next push or edit" in flat
    assert "skipped and passing" in flat
    assert "`pyproject.toml`" in flat
    # A PR the condition skips gets no notice; the notice is the Gate's, on a PR the condition
    # admits (finding 3 of the review of .github#60). The mode is read without case (finding 1).
    assert "passes any other with a notice" not in flat
    assert "passes every pull request with a notice" not in flat
    assert "the Gate's notice" in flat
    assert "read without case" in flat
    assert "sdk-core" not in section
    assert "`--docs`" not in README
    # The events the job runs on, and that a caller on more events changes nothing for it.
    assert (
        "the job runs on a pull request's opening, push, reopening and edit alone, the event "
        "`pull_request` with the types `opened`, `synchronize`, `reopened` and `edited`, and is "
        "skipped on any other event of its caller" in flat
    )
    assert "`github.event_name` and `github.event.action`" in flat
    assert "a caller that runs on those four alone sees no change" in flat


def test_the_gate_and_the_docstring_name_the_mode_and_its_two_values() -> None:
    """The Gate's docstring and the script's name the mode and its two values (step 1.1 of
    .github 0.5.0); the workflow carries no comment that could say otherwise (step 2.1)."""
    gate_comment = " ".join(str(fr.gate.__doc__).replace("``", "`").split())
    assert "The caller's WORKFLOW_CONVENTIONS_MODE, `release` when neither" in gate_comment
    assert "`Off`" not in gate_comment
    assert "WORKFLOW_CONVENTIONS_MODE" in " ".join(fr.__doc__.split())
    assert "naming the three" not in gate_comment
    assert "#" not in WORKFLOW.split("\njobs:\n", 1)[1].split("\n    steps:\n", 1)[0]


def test_the_readmes_callers_run_on_no_label() -> None:
    """The wiring's text gives the four types a caller of coordinate-core 0.7.6 runs on, and the
    trigger file `conventions.yml` runs on them, while `spelling.yml` and `adr-index.yml` run on
    the first three, since an edit starts the review only (finding 1 of the review of
    .github#115); none runs on `labeled`, and the text says that a label set after the opening
    counts from the next push or edit (.github#68, C57 as amended by coordinate-core#1059). The
    conditions of the trigger file `conventions.yml` are held by test_trigger_files.py."""
    section = README.split("## Wiring and check contexts", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(section.split())
    callers = [block.split("```", 1)[0] for block in section.split("```yaml\n")[1:]]
    assert len(callers) == 3
    assert "`opened`, `synchronize`, `reopened` and `edited`" in flat
    assert "    types: [opened, synchronize, reopened, edited]\n" in callers[0]
    for caller in callers[1:]:
        assert "    types: [opened, synchronize, reopened]\n" in caller
    assert "labeled" not in section
    assert "uses: xippios/.github/.github/workflows/conventions.yml@main" in callers[0]
    assert "A label set after the opening" in flat
    assert "counts from the next push or edit" in flat


def test_the_readme_lays_out_the_keys_of_the_secret() -> None:
    """The secret holds one key or several, one per line, tried in order; a refused key starts
    the review again on the next, and the summary line names the key that served
    (.github#87)."""
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/site-tests.yml`**", 1)[0]
    text = " ".join(section.split())
    assert "one key or several, one per line" in text
    assert "starts again from its first turn on the next key" in text
    assert "`key=2/3`" in text
    assert "says nothing of keys" in text


def test_the_readme_says_a_refusal_inside_the_stream_and_the_type_of_an_error() -> None:
    """The item on the keys says that an error whose message names the balance refuses the key
    whatever its status, an error event of the stream among them, and that each line of an error
    of the API names its type where its body gives a code, and no text of it (.github#163)."""
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    item = section.split("- **The keys**", 1)[1].split("\n  - **", 1)[0]
    text = " ".join(item.split())
    assert "a 400 whose message names the balance" not in text
    assert (
        "and an error whose message names the balance of the account, whatever its status and "
        "its type: a 400 before the stream, or an error event of the stream under the stream's "
        "status 200 (https://github.com/xippios/.github/issues/163)" in text
    )
    assert "`API error: APIStatusError of type overloaded_error (request req_…) after 3 tries`" in (
        text
    )
    assert (
        "Every line that names an error of the API by its class, in the job log and the summary "
        "alike, names beside it the type that the error's body gives, as `of type "
        "overloaded_error`, where that type is a code of lowercase letters and underscores, and "
        "no type where the body gives none or another text; no line carries the error's message "
        "(https://github.com/xippios/.github/issues/121)." in text
    )


def test_the_readme_and_the_docstring_name_the_judge_the_script_runs() -> None:
    """The README's sentence on the judge and on the turn cap and the script's docstring name
    the model, the effort and the turn cap that the script runs with (.github#93)."""
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/site-tests.yml`**", 1)[0]
    for text in (section, fr.__doc__):
        flat = " ".join(text.replace("`", "").split())
        assert f"{fr.MODEL}, at effort {fr.EFFORT}" in flat
        assert f"the turn cap of {fr.MAX_TURNS}" in flat


def test_the_job_times_out_after_45_minutes_and_the_texts_say_so() -> None:
    """The job's timeout leaves a review at effort xhigh the time of 160 turns on one key, since
    the turns start again on the next, and the README names it beside the turn cap: a review
    the timeout ends writes no summary line, while `prepare` has written its own lines to the
    job summary before (findings 1 of the reviews of .github#94)."""
    assert "    timeout-minutes: 45\n" in WORKFLOW
    assert "timeout-minutes: 30" not in WORKFLOW
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/site-tests.yml`**", 1)[0]
    text = " ".join(section.split())
    assert "The job times out after 45 minutes" in text
    assert "the time of 160 turns on one key" in text
    assert "a review the timeout ends returns no verdict and writes no summary line" in text
    assert "no line of the script" not in text


def test_the_readme_says_the_sdks_retries_of_a_429_alone() -> None:
    """The SDK retries a 429 status, never a stream it has begun, so a `rate_limit_error` that
    an error event of the stream carries moves the review to the next key at once (finding 1
    of the review of .github#90)."""
    flat = " ".join(README.split())
    assert "A rate limit reaches the script only once" not in flat
    assert "A 429 reaches the script only once the SDK's own retries are spent" in flat
    assert "the SDK retries no stream it has begun" in flat
    assert "moves the review to the next key at once" in flat


def test_the_readme_runs_the_review_locally_on_a_release_pr_as_the_workflow() -> None:
    section = README.split("## Running the review locally", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(section.split())
    assert "a pull request labeled `release` or titled `<version> Release` on its release's" in flat
    assert "`release: <version>`" not in flat


# --- the read token (.github#62) ---------------------------------------------------------

# Only a private caller's check gets the secret (.github#83): GitHub's `case()` returns its
# last argument where no predicate is true, and `github.event` of a called workflow is the
# caller's payload, whose `repository.private` is a boolean.
READ_TOKEN_VALUE = (
    "          DOCUMENTS_READ_TOKEN: ${{ case(github.event.repository.private == true, "
    "secrets.DOCUMENTS_READ_TOKEN, '') }}\n"
)
READ_TOKEN_UNUSED = (
    "          READ_TOKEN_UNUSED: ${{ secrets.DOCUMENTS_READ_TOKEN != '' "
    "&& github.event.repository.private != true }}\n"
)
UNUSED_NOTICE = (
    "conventions: DOCUMENTS_READ_TOKEN is not used in a public repository, whose review "
    "comment and job summary would show what the review quotes from a private document "
    "(.github#83)"
)


def test_the_read_token_reaches_a_private_callers_prepare_step_alone() -> None:
    """The caller may pass DOCUMENTS_READ_TOKEN; only the step that reads the documents gets
    it, and only where the calling repository is private. The Gate learns whether a public
    caller passed one, never its value; the review, the verdict and a checkout get nothing."""
    secrets = WORKFLOW.split("  workflow_call:\n    secrets:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "      ANTHROPIC_API_KEY:\n        required: false\n" in secrets
    assert "      DOCUMENTS_READ_TOKEN:\n        required: false\n" in secrets
    assert WORKFLOW.count("secrets.DOCUMENTS_READ_TOKEN") == 2
    assert "${{ secrets.DOCUMENTS_READ_TOKEN }}" not in WORKFLOW
    assert READ_TOKEN_VALUE in step_block("Prepare the review material")
    assert READ_TOKEN_UNUSED in step_block("Gate")
    for name in (
        "Check out the pull request head with full history",
        "Check out the review script from xippios/.github",
        "Install uv",
        "Review",
        "Verdict",
    ):
        # A block runs up to the next step and takes in the comment above it: no key, no value.
        assert "DOCUMENTS_READ_TOKEN:" not in step_block(name)
        assert "secrets.DOCUMENTS_READ_TOKEN" not in step_block(name)


def test_a_public_caller_that_passes_the_read_token_gets_a_notice_where_the_review_runs(
    tmp_path: Path,
) -> None:
    code, out, outputs = gate(tmp_path, mode="all", read_token_unused=True)
    assert code == 0
    assert outputs["run"] == "true"
    assert UNUSED_NOTICE in out


@pytest.mark.parametrize(("mode", "unused"), [("all", False), ("release", True)])
def test_no_notice_on_the_read_token_where_it_is_used_or_nothing_is_read(
    tmp_path: Path, mode: str, unused: bool
) -> None:
    """A private caller, or a caller without the secret; a pull request the mode passes."""
    _code, out, _outputs = gate(tmp_path, mode=mode, read_token_unused=unused)
    assert "DOCUMENTS_READ_TOKEN" not in out


def test_the_readme_lays_out_the_read_token_and_its_caller() -> None:
    """The documents' text names the token, that only a private caller's check uses it and
    why, and what a pull request cannot choose of what the check reads, which bounds the
    check and not the secret (.github#62, .github#83). The sample trigger file passes the key
    alone, and the README names no caller's secret `DOCUMENTS_READ_TOKEN`: a trigger file fills
    the workflows' secret of that name from its workspace's own (.github#149)."""
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/site-tests.yml`**", 1)[0]
    flat = " ".join(section.split())
    assert "`DOCUMENTS_READ_TOKEN`" in flat
    # The name is the workflow's own secret, which a caller fills from its own (finding 1 of the
    # review of .github#150).
    assert "an optional secret of the caller" not in flat
    assert (
        "`DOCUMENTS_READ_TOKEN`, an optional secret of the workflow's own call, which a trigger "
        "file fills from the secret of its workspace" in flat
    )
    assert "fails the check on a private one" not in flat
    assert "only where the calling repository is private" in flat
    assert "`github.event.repository.private`" in flat
    assert "quote the documents it judges by" in flat
    assert "to everyone who reads that repository" in flat
    assert "a pull request chooses nothing but a release tag" in flat
    assert "chooses nothing the token reads" not in flat
    assert "the organization's setting" in flat
    wiring = README.split("## Wiring and check contexts", 1)[1].split("\n## ", 1)[0]
    caller = wiring.split("```yaml\n", 1)[1].split("```", 1)[0]
    # The trigger file `conventions.yml` passes the key by name to each of its two jobs, and
    # leaves the read token's line out, as a repository that reads no private document does.
    assert caller.count("      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}\n") == 2
    assert "DOCUMENTS_READ_TOKEN" not in caller
    assert "secrets.DOCUMENTS_READ_TOKEN" not in README
    assert "inherit" not in caller
    assert "exactly one secret" not in " ".join(wiring.split())
    # Where the read token is needed is prose, since a trigger file carries no comment.
    assert "#" not in caller
    assert "only in a private repository whose README lists a private repository's document" in (
        " ".join(wiring.split())
    )


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
    env = verdict_env(
        tmp_path,
        result,
        last_comment=last_comment,
        view_fails=view_fails,
        comment_fails=comment_fails,
    )
    done = run_step("Verdict", env)
    (tmp_path / "stdout.txt").write_text(done.stdout)
    comment_file = tmp_path / "bin" / "comment.md"
    comment = comment_file.read_text() if comment_file.exists() else None
    summary = (tmp_path / "summary.md").read_text()
    return done.returncode, summary + done.stderr, gh_calls(tmp_path), comment


def verdict_env(
    tmp_path: Path,
    result: dict | None,
    *,
    last_comment: str = "",
    view_fails: bool = False,
    comment_fails: bool = False,
) -> dict[str, str]:
    """The environment of the Verdict step: the job's, with ``result`` as the verdict file in
    the runner's temporary directory, and the values its `env:` block gives. The stub `gh`
    answers the view of the last comment and keeps the comment it is given."""
    view = "exit 1" if view_fails else 'cat "$here/last.txt"'
    post = 'cat > "$here/comment.md"'
    if comment_fails:
        post = "echo 'HTTP 403: Resource not accessible by integration (ghs_abc123)' >&2; exit 1"
    gh = (
        "#!/bin/sh\n"
        'here=$(dirname "$0")\n'
        'printf "%s\\n" "$*" >> "$here/calls"\n'
        'case "$1 $2" in\n'
        f'  "pr view") {view} ;;\n'
        f'  "pr comment") {post} ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n"
    )
    env = job_env(tmp_path, gh)
    bin_dir = tmp_path / "bin"
    (bin_dir / "last.txt").write_text(last_comment)
    (bin_dir / "comment.md").unlink(missing_ok=True)
    result_file = Path(env["RUNNER_TEMP"]) / "verdict.json"
    result_file.unlink(missing_ok=True)
    if result is not None:
        result_file.write_text(json.dumps(result))
    return {
        **env,
        "RESULT_FILE": str(result_file),
        "GH_TOKEN": "dummy",
        "REPO": REPO,
        "PR": "11",
        "HEAD_SHA": SHA,
    }


# The two fields of the script's `--out` document that no output shows (.github#65), as
# `Outcome.as_json` writes them, so the exact comparisons below hold that the step leaves them
# out of the job summary, the log and the comment.
KEPT = {
    key: value
    for key, value in fr.Outcome(
        model=fr.MODEL,
        effort=fr.EFFORT,
        usage=fr.Usage(input=1_000_000, cache_write=2_000_000, cache_read=3_000_000, output=4_000),
    )
    .as_json()
    .items()
    if key in ("cost_estimate_usd", "cost_estimate_basis")
}


def result(verdict: str, findings: list[dict], *, release: bool = False) -> dict:
    return {
        "verdict": verdict,
        "findings": findings,
        "range": {"release": release, "since": "a" * 40, "tag": "v0.6.3" if release else None},
        "documents": ["sdk-core: docs/conventions.md", "sdk-usda-psd: docs/conventions.md"],
        "summary": "conventions: verdict=…",
        **KEPT,
    }


def test_the_fixture_carries_the_fields_the_document_keeps() -> None:
    assert set(KEPT) == {"cost_estimate_usd", "cost_estimate_basis"}
    assert KEPT["cost_estimate_usd"] > 0


def finding(document: str, text: str, file: str = "src/pkg/mod.py", line=2, blocking=False):
    return {"document": document, "file": file, "line": line, "blocking": blocking, "text": text}


FIELDS = ("document", "file", "line", "blocking", "text")


def block(findings: list[dict], head: str = SHA) -> str:
    """The hidden last line of the comment, which carries this run to the next (.github#95):
    the head and the findings, `<` and `>` escaped so no text ends the HTML comment."""
    run = {"head": head, "findings": [{key: f[key] for key in FIELDS} for f in findings]}
    blob = json.dumps(run, ensure_ascii=True, separators=(",", ":"))
    return "<!-- conventions-run: " + blob.replace("<", "\\u003c").replace(">", "\\u003e") + " -->"


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
        "3. **`src/pkg/cli.py:7`** A stray print. Blocks: no.\n\n"
        f"{block(findings)}\n"
    )
    assert summary == expected
    assert (tmp_path / "stdout.txt").read_text() == expected + "\n"
    assert comment == expected
    assert calls[-1].startswith("pr comment 11 --edit-last --create-if-none --body-file -")


def test_the_comment_says_nothing_of_keys(tmp_path: Path) -> None:
    """A review that a later key of the secret served posts the comment of one the first key
    served (.github#87)."""
    first = verdict_step(tmp_path, result("ready", []))[3]
    later = {**result("ready", []), "summary": "conventions: verdict=ready key=2/3"}
    code, summary, _calls, comment = verdict_step(tmp_path, later)
    assert code == 0
    assert comment == first
    assert "key" not in summary.lower()


def test_an_approval_without_findings_passes_and_creates_the_comment(tmp_path: Path) -> None:
    code, summary, calls, comment = verdict_step(tmp_path, result("ready", []))
    assert code == 0
    assert summary == (
        f"{MARKER}\n**Approved.** No findings at {COMMIT}.\n\n"
        "Judged: the pull request's own diff, against 2 documents of `README.md` on `main`.\n\n"
        f"{block([])}\n"
    )
    assert (tmp_path / "stdout.txt").read_text() == summary + "\n"
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


@pytest.mark.parametrize("verdict", ["ready", "not ready"])
def test_a_comment_with_the_old_marker_is_no_comment_of_the_check(
    tmp_path: Path, verdict: str
) -> None:
    """The marker from before the markers of the style is retired (step 2.1 of .github 0.5.0):
    the token's last comment that opens with it is another's, so the verdict posts a new
    comment and edits none."""
    findings = [] if verdict == "ready" else [finding("", "A stray print.", blocking=True)]
    old = "<!-- conventions -->\n## conventions: `not ready`\n"
    code, summary, calls, comment = verdict_step(
        tmp_path, result(verdict, findings), last_comment=old
    )
    assert code == (0 if verdict == "ready" else 1)
    assert comment == summary
    assert comment.startswith(f"{MARKER}\n")
    assert calls == [VIEW, CREATE]
    assert fr.CHECK_MARKERS == (MARKER,)


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
        {
            "verdict": None,
            "summary": "conventions: no verdict (the turn cap of 160 was reached)",
            **KEPT,
        },
    )
    assert code == 1
    assert summary == (
        "## conventions: no verdict\n\n"
        "conventions: no verdict (the turn cap of 160 was reached)\n\n"
        "The review returned no verdict; the check fails.\n"
    )
    assert (tmp_path / "stdout.txt").read_text() == summary + "\n"
    assert comment is None
    assert calls == []
    code, summary, _calls, _comment = verdict_step(tmp_path, None)
    assert code == 1
    assert "the review wrote no result" in summary


# --- the run before (.github#95) ---------------------------------------------------------

BEFORE = "e" * 40


def test_the_comment_tells_what_became_of_each_finding_of_the_run_before(tmp_path: Path) -> None:
    """Each new finding says whether its file changed since the head judged before; the
    findings of the run before follow, each fixed, decided by the opener or open."""
    new = [
        {
            **finding(
                "sdk-core: docs/conventions.md#tests", "The test commit is missing.", blocking=True
            ),
            "since": "unchanged",
        },
        {**finding("", "A stray print.", file="src/pkg/cli.py", line=7), "since": "changed"},
        {**finding("", "Another.", file="src/pkg/x.py", line=None), "since": "not compared"},
        finding("", "The body has no proof.", file="", line=None),
    ]
    earlier = {
        "head": BEFORE,
        "findings": [
            {
                **finding("sdk-core: docs/conventions.md#names", "A name departs."),
                "state": "fixed",
                "finding": None,
            },
            {
                **finding("", "The body cites no row.", file="", line=None),
                "state": "decided",
                "finding": None,
            },
            {
                **finding(
                    "sdk-core: docs/conventions.md#tests",
                    "The test commit is missing.",
                    blocking=True,
                ),
                "state": "open",
                "finding": 1,
                "reason": "The commit  holds no test.",
            },
            {
                **finding("sdk-core: docs/conventions.md#ci", "No ci badge.", blocking=True),
                "state": "decided",
                "finding": None,
                "reason": "The rule names release PRs alone",
            },
        ],
    }
    code, summary, calls, comment = verdict_step(
        tmp_path, {**result("not ready", new), "earlier": earlier}
    )
    assert code == 1
    expected = (
        f"{MARKER}\n**Blocked.** 4 findings, 1 blocking, at {COMMIT}.\n\n"
        "Judged: the pull request's own diff, against 2 documents of `README.md` on `main`.\n\n"
        "1. **sdk-core: docs/conventions.md#tests** The test commit is missing. "
        "`src/pkg/mod.py:2`. Blocks: yes. Its file is unchanged since the head judged before.\n"
        "2. **`src/pkg/cli.py:7`** A stray print. Blocks: no. Its file changed since the head "
        "judged before.\n"
        "3. **`src/pkg/x.py`** Another. Blocks: no. Its file was not compared: the head judged "
        "before could not be read.\n"
        "4. **the pull request** The body has no proof. Blocks: no.\n\n"
        f"The run before judged https://github.com/{REPO}/commit/{BEFORE} and gave 4 findings:\n\n"
        "1. **sdk-core: docs/conventions.md#names** A name departs. `src/pkg/mod.py:2`. Fixed.\n"
        "2. **the pull request** The body cites no row. Decided by the opener.\n"
        "3. **sdk-core: docs/conventions.md#tests** The test commit is missing. "
        "`src/pkg/mod.py:2`. Open: finding 1 above. The opener decided otherwise, and the rule "
        "stands: The commit holds no test.\n"
        "4. **sdk-core: docs/conventions.md#ci** No ci badge. `src/pkg/mod.py:2`. Decided by the "
        "opener: The rule names release PRs alone.\n\n"
        f"{block(new)}\n"
    )
    assert comment == expected
    assert summary == expected
    assert calls == [VIEW, EDIT]


def test_a_run_before_without_findings_is_named_by_its_head(tmp_path: Path) -> None:
    new = [{**finding("", "A stray print.", file="src/pkg/cli.py", line=7), "since": "unchanged"}]
    earlier = {"head": BEFORE, "findings": []}
    _code, _summary, _calls, comment = verdict_step(
        tmp_path, {**result("ready", new), "earlier": earlier}
    )
    assert comment is not None
    assert comment.endswith(
        "1. **`src/pkg/cli.py:7`** A stray print. Blocks: no. Its file is unchanged since the "
        "head judged before.\n\n"
        f"The run before judged https://github.com/{REPO}/commit/{BEFORE} and gave no findings."
        f"\n\n{block(new)}\n"
    )


def test_a_first_run_tells_of_no_run_before(tmp_path: Path) -> None:
    findings = [finding("", "A stray print.", file="src/pkg/cli.py", line=7)]
    _code, _summary, _calls, comment = verdict_step(tmp_path, result("ready", findings))
    assert comment is not None
    assert "run before" not in comment
    assert "since the head judged before" not in comment


def test_the_next_run_reads_the_run_the_comment_carries(tmp_path: Path) -> None:
    """What the Verdict step writes, the next run's prepare reads: no text of a finding ends the
    hidden line early, and a key in it stays redacted."""
    key = "sk-ant-" + "api03-" + "Zx9" * 8
    findings = [
        finding("doc#a", "Ends early --> or <b>not</b>.\nOn two lines.", blocking=True),
        finding("", f"Key {key} here.", file="", line=None),
    ]
    _code, _summary, _calls, comment = verdict_step(tmp_path, result("not ready", findings))
    assert comment is not None
    last = comment.splitlines()[-1]
    assert last == block([findings[0], {**findings[1], "text": "Key [redacted] here."}])
    assert "<" not in last.removeprefix("<!--")
    run = fr.run_state(comment)
    assert run is not None
    assert run.head == SHA
    assert run.findings == [findings[0], {**findings[1], "text": "Key [redacted] here."}]


def test_the_readme_lays_out_the_run_before() -> None:
    section = README.split("**`.github/workflows/conventions.yml`**", 1)[1]
    section = section.split("**`.github/workflows/site-tests.yml`**", 1)[0]
    text = " ".join(section.split())
    assert "the run before" in text
    assert "fixed, decided by the opener or open" in text
    assert "whether its file changed since the head judged before" in text
    assert "by the text of its files, not by ancestry" in text
    assert "could not be read" in text
    assert "judges as a first run" in text
    assert "names a line only where its file has that line at the head" in text
    # Findings 1, 3 and 8 of the review of .github#104.
    assert "a file the head's tree holds" in text
    assert "never settles a finding that blocked" in text
    assert "no run before was found" in text
    dry_run = README.split("## Running the review locally", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(dry_run.split())
    assert (
        "`--earlier <file>` takes the verdict file that an earlier dry run wrote with `--out`"
        in (flat)
    )
    assert "prints the states and the marks as the comment shows them" in flat


def test_an_earlier_finding_that_no_longer_blocks_says_so_with_its_reason(tmp_path: Path) -> None:
    """An earlier finding that blocked and is carried by one that does not block prints the
    judge's reason, in the words of `became` in conventions.py (finding 1 of the second review
    of .github#104)."""
    new = [finding("sdk-core: docs/conventions.md#ci", "No ci badge.")]
    before = {
        **finding("sdk-core: docs/conventions.md#ci", "No ci badge.", blocking=True),
        "state": "open",
        "finding": 1,
        "reason": "The rule binds release PRs alone",
        "unblocked": True,
    }
    earlier = {"head": BEFORE, "findings": [before]}
    _code, _summary, _calls, comment = verdict_step(
        tmp_path, {**result("ready", new), "earlier": earlier}
    )
    assert comment is not None
    words = fr.became(before)
    assert words == (
        "Open: finding 1 above. It blocked before and no longer blocks: The rule binds release "
        "PRs alone."
    )
    assert (
        f"1. **sdk-core: docs/conventions.md#ci** No ci badge. `src/pkg/mod.py:2`. {words}\n"
        in (comment)
    )
