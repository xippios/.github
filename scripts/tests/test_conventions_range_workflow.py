"""`conventions-range.yml`, the conventions review of a range of commits (.github#96), is callable
with its final secrets and permissions (step 1 of .github 0.5.0, .github#102): a trigger file that
calls it on a push to `main` or on a dispatch grants from the start what it asks for, since a
caller that grants less than a called workflow asks for fails at its start. Its first job, `gate`,
knows the merge that completes a package (step 3 of .github 0.5.0, .github#99): it runs on a push
and on a dispatch alone, with permissions narrower than the workflow's, and calls
`conventions.py range-gate` once from the script's checkout, the values in its `env:` block.

The job `range` judges and reports (step 3.1 of .github 0.5.0, .github#129): it needs the gate
and runs where the gate wrote `run` as `true`, so its check `range / range` reports as skipped
where the gate did not let it run or failed, and a check that passed always stands for a range
that was judged. It narrows its permissions to what it uses, times out as the review of a pull
request does and cancels the older run of its repository and ref. It fails on a missing key
before the caller's commit is checked out, checks the commit out with its full history and the
script again, and calls the script once for each of prepare, review and verdict, the values in
`env:` blocks. The file carries no comment but the version after a pinned action (.github#111).

The tests evaluate the job's needs and condition as the file holds them with `expressions.py`
and GitHub's rule for a job that needs another, and run its steps' own `run:` texts in the
environment the runner gives a step, with a stub `gh` (stub_gh.py) and a stub `uv` that runs the
script on the suite's Python."""

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import stub_gh
from expressions import holds, runs
from workflow_yaml import parse

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "conventions.py"
WORKFLOWS = ROOT / ".github" / "workflows"
PATH = WORKFLOWS / "conventions-range.yml"
TEXT = PATH.read_text()
REVIEW_TEXT = (WORKFLOWS / "conventions.yml").read_text()
README = (ROOT / "README.md").read_text()
SECRETS = ("ANTHROPIC_API_KEY", "DOCUMENTS_READ_TOKEN")
# The version after an action pinned to a commit, the one comment a workflow file keeps.
VERSION = re.compile(r"(uses: [A-Za-z0-9_./-]+@[0-9a-f]{40}) # v?[0-9]+(?:\.[0-9]+)*$", re.M)
CONDITION = "github.event_name == 'push' || github.event_name == 'workflow_dispatch'"
CALL = 'python3 -I "$GITHUB_WORKSPACE/.sdk-gates/scripts/conventions.py" range-gate'
# The values the step `Gate` hands the script, each from the caller's event or the token.
GATE_ENV = {
    "EVENT": "${{ github.event_name }}",
    "SHA": "${{ github.sha }}",
    "REPO": "${{ github.repository }}",
    "REF": "${{ github.ref }}",
    "DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
    "GH_TOKEN": "${{ github.token }}",
}
REPO = "xippios/sdk-usda-psd"
COMMIT = "c" * 40
EMPTY_KEY = (
    "conventions: ANTHROPIC_API_KEY is empty; the review cannot run. Share the organization "
    "secret with this repository (G4)."
)
RANGE_CONDITION = "needs.gate.outputs.run == 'true'"
STEPS = [
    "Check out the script for the key from xippios/.github",
    "Key",
    "Check out the commit with full history",
    "Check out the review script from xippios/.github",
    "Install uv",
    "Prepare the range material",
    "Review",
    "Verdict",
]


def workflow() -> dict:
    """The workflow up to the job `range`, as the strict reader reads it, which refuses any
    comment, a quoted scalar and a block scalar: the version after a pinned action is taken off
    first, and the steps of the job `range` are read by `range_steps`."""
    return parse(VERSION.sub(r"\1", TEXT.split("\n  range:\n", 1)[0]))


def gate() -> dict:
    return workflow()["jobs"]["gate"]


def test_the_workflow_is_titled_conventions_range() -> None:
    assert workflow()["name"] == "Conventions range"


def test_it_is_callable_alone_with_the_two_secrets_of_the_review_both_optional() -> None:
    on = workflow()["on"]
    assert list(on) == ["workflow_call"]
    assert on["workflow_call"] == {"secrets": {name: {"required": "false"} for name in SECRETS}}
    # The same two as the review of a pull request, so a trigger file passes both to each.
    central = REVIEW_TEXT.split("  workflow_call:\n    secrets:\n", 1)[1].split("\npermissions:")[0]
    for name in SECRETS:
        assert f"      {name}:\n        required: false\n" in central


def test_it_asks_for_its_final_permissions() -> None:
    """The workflow's block stays as step 1 gave it, the final hand-over of a trigger file."""
    assert workflow()["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "checks": "read",
        "issues": "read",
    }


def test_the_gate_comes_first_and_the_range_after_it() -> None:
    jobs = TEXT.split("\njobs:\n", 1)[1]
    assert re.findall(r"^  ([a-z-]+):$", jobs, re.M) == ["gate", "range"]


# --- the job gate ------------------------------------------------------------------------


def test_the_gate_is_named_for_its_check_and_times_out_after_five_minutes() -> None:
    job = gate()
    # The job's name joins the caller's job id `range` to the context `range / gate`.
    assert job["name"] == "gate"
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == "5"
    assert "needs" not in job
    assert "uses" not in job


def test_the_gate_holds_its_condition() -> None:
    assert gate()["if"] == CONDITION
    assert "vars." not in CONDITION
    assert "secrets." not in TEXT.split("\n  range:\n", 1)[0].split("\njobs:\n", 1)[1]


@pytest.mark.parametrize(
    ("event", "admitted"),
    [
        ("push", True),
        ("workflow_dispatch", True),
        ("pull_request", False),
        ("schedule", False),
        ("pull_request_target", False),
        ("merge_group", False),
    ],
)
def test_the_gate_runs_on_a_push_and_on_a_dispatch_alone(event: str, admitted: bool) -> None:
    """A called workflow reads its caller's `github.event_name`; the switch is the trigger
    file's."""
    for variables in ({}, {"WORKFLOW_CONVENTIONS": "off"}):
        assert runs(gate()["if"], event, variables) == admitted


def test_the_gate_narrows_its_permissions_to_its_reads() -> None:
    """It reads the commit's pull requests, the milestone's issues and the closing issues of a
    pull request, and writes nothing."""
    assert gate()["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
        "issues": "read",
    }


def test_the_gate_hands_its_two_outputs_to_the_jobs_after_it() -> None:
    assert gate()["outputs"] == {
        "run": "${{ steps.gate.outputs.run }}",
        "pr": "${{ steps.gate.outputs.pr }}",
    }


def first_step(text: str) -> str:
    """The text of the first step of the first job of a workflow, up to the step `Gate`."""
    return text.split("\n    steps:\n", 1)[1].split("\n\n      - name: Gate\n", 1)[0]


def test_the_gate_checks_the_script_out_as_the_review_of_a_pull_request_does() -> None:
    """The same step as the first of conventions.yml: the script at the workflow's own commit,
    into `.sdk-gates`, with no credential kept."""
    assert first_step(TEXT) == first_step(REVIEW_TEXT)
    checkout, _step = gate()["steps"]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {
        "repository": "xippios/.github",
        "ref": "${{ job.workflow_sha }}",
        "path": ".sdk-gates",
        "persist-credentials": "false",
    }


def test_the_gate_is_one_call_of_the_script_with_the_values_in_its_env() -> None:
    _checkout, step = gate()["steps"]
    assert step == {"name": "Gate", "id": "gate", "env": GATE_ENV, "run": CALL}
    assert "${{" not in step["run"]
    assert "uv " not in TEXT.split("\n  range:\n", 1)[0]


def test_the_workflow_holds_no_inline_code() -> None:
    """No `run:` feeds Python a here-document or a `-c` program: the code is the script's. The
    blocks of shell are Prepare's check of the link with its call and Review's call, as in
    conventions.yml."""
    assert "<<" not in TEXT
    assert re.search(r"python3?( -[A-Za-z]+)* -( |$)", TEXT, re.M) is None
    assert re.search(r"python3?( -[A-Za-z]+)* -c\b", TEXT) is None
    blocks = [name for name, block in range_steps() if "\n        run: |\n" in block]
    assert blocks == ["Prepare the range material", "Review"]
    assert TEXT.count("run: |") == 2


def test_the_actionlint_ignore_of_the_jobs_workflow_commit_covers_the_file() -> None:
    """actionlint 1.7.12 does not know `job.workflow_sha`, which the checkout of the script reads
    here as in conventions.yml."""
    config = (ROOT / ".github" / "actionlint.yaml").read_text()
    ignore = (
        "    ignore:\n"
        "      - 'property \"workflow_sha\" is not defined in object type \\{check_run_id'\n"
    )
    for name in ("conventions.yml", "conventions-range.yml"):
        assert f"  .github/workflows/{name}:\n{ignore}" in config, name
        assert "job.workflow_sha" in (WORKFLOWS / name).read_text()


def test_the_file_carries_no_comment_but_the_version_of_a_pinned_action() -> None:
    assert "#" not in VERSION.sub(r"\1", TEXT)


# --- the job range -----------------------------------------------------------------------

RANGE_TEXT = TEXT.split("\n  range:\n", 1)[1]


def range_job() -> dict:
    """The job `range` up to its steps, as the strict reader reads it."""
    return parse(textwrap.dedent(RANGE_TEXT.split("\n    steps:\n", 1)[0]))


def range_steps() -> list[tuple[str, str]]:
    """The steps of the job `range` in order, each its name and its block up to the next."""
    steps = RANGE_TEXT.split("\n    steps:\n", 1)[1]
    blocks = re.split(r"^      - name: ", steps, flags=re.M)[1:]
    return [(block.split("\n", 1)[0], block.rstrip("\n")) for block in blocks]


def review_steps() -> list[tuple[str, str]]:
    """The steps of the job `conventions` of conventions.yml, read alike."""
    steps = REVIEW_TEXT.split("\n    steps:\n", 1)[1]
    blocks = re.split(r"^      - name: ", steps, flags=re.M)[1:]
    return [(block.split("\n", 1)[0], block.rstrip("\n")) for block in blocks]


def range_step(name: str) -> str:
    return dict(range_steps())[name]


def without_condition(block: str) -> str:
    """A step's block without its `if:` line."""
    return "\n".join(line for line in block.splitlines() if not line.startswith("        if: "))


def run_of(block: str) -> str:
    """The `run:` script of a step's block: a block scalar or one line."""
    run = ("\n" + block).split("\n        run: ", 1)[1]
    if not run.startswith("|\n"):
        return run.split("\n", 1)[0] + "\n"
    script = []
    for line in run[2:].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        script.append(line[10:])
    return "\n".join(script) + "\n"


def env_of(block: str) -> dict[str, str]:
    """The `env:` block of a step, each name and its value as written."""
    env = block.split("\n        env:\n", 1)[1].split("\n        run: ", 1)[0]
    return dict(line.strip().split(": ", 1) for line in env.splitlines())


def test_the_range_is_named_for_its_check_and_needs_the_gate() -> None:
    job = range_job()
    # The job's name joins the caller's job id `range` to the context `range / range`.
    assert job["name"] == "range"
    assert job["needs"] == "gate"
    assert job["if"] == RANGE_CONDITION
    assert job["runs-on"] == "ubuntu-latest"
    # No status function: GitHub runs the job only where every job it needs succeeded.
    assert re.search(r"\b(?:always|success|failure|cancelled)\(", job["if"]) is None


def range_runs(results: dict[str, str], outputs: dict[str, str]) -> bool:
    """Whether the job `range` starts, as GitHub decides for a job whose condition calls no
    status function: every job it needs succeeded, and then its condition holds on their
    outputs. An output that a job did not write reads as ''."""
    job = range_job()
    needed = [job["needs"]] if isinstance(job["needs"], str) else job["needs"]
    if any(results[name] != "success" for name in needed):
        return False
    context = {"needs": {name: {"result": results[name], "outputs": outputs} for name in needed}}
    return holds(job["if"], context)


@pytest.mark.parametrize(
    ("result", "outputs", "started"),
    [
        ("success", {"run": "true", "pr": "7"}, True),
        ("success", {"run": "true", "pr": ""}, True),
        ("success", {"run": "false", "pr": "7"}, False),
        ("success", {"run": "false", "pr": ""}, False),
        ("failure", {"run": "false", "pr": ""}, False),
        ("failure", {"run": "", "pr": ""}, False),
        ("skipped", {"run": "", "pr": ""}, False),
        ("cancelled", {"run": "", "pr": ""}, False),
    ],
)
def test_the_range_starts_where_the_gate_ran_and_said_yes_alone(
    result: str, outputs: dict[str, str], started: bool
) -> None:
    """A gate that said no, failed or was skipped leaves the job skipped: `range / range` then
    reports as skipped, so a passed check stands for a judged range."""
    assert range_runs({"gate": result}, outputs) is started


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "pull_request", "schedule"])
def test_the_range_is_skipped_on_every_event_the_gate_skips(event: str) -> None:
    result = "success" if runs(gate()["if"], event, {}) else "skipped"
    started = range_runs({"gate": result}, {"run": "" if result == "skipped" else "true"})
    assert started is (event in ("push", "workflow_dispatch"))


def test_the_range_narrows_its_permissions_to_what_it_uses() -> None:
    """It reads the commit and the documents, reads the merged pull request and its comments,
    and writes one comment there; it reads the checks of the commits of its line, the runs
    before it builds on (step 4 of .github 0.5.0); the issues are the gate's."""
    permissions = range_job()["permissions"]
    assert permissions == {"contents": "read", "pull-requests": "write", "checks": "read"}
    assert permissions.items() <= workflow()["permissions"].items()


def test_the_range_times_out_as_the_review_and_cancels_the_older_run_of_its_ref() -> None:
    job = range_job()
    review_timeout = re.search(r"^    timeout-minutes: ([0-9]+)$", REVIEW_TEXT, re.M)
    assert job["timeout-minutes"] == review_timeout.group(1) == "45"
    assert job["concurrency"] == {
        "group": "conventions-range-${{ github.repository }}-${{ github.ref }}",
        "cancel-in-progress": "true",
    }


def test_the_steps_come_in_their_order() -> None:
    assert [name for name, _block in range_steps()] == STEPS


def test_the_key_is_checked_before_the_commit_is_checked_out() -> None:
    """The first step checks the script out as the gate's does; the Key step calls it once with
    whether the caller passed a key, as the Gate of a pull request learns it."""
    (_first, block), (second, key) = range_steps()[:2]
    gate_first = first_step(TEXT).split("\n", 1)[1]
    assert block.split("\n", 1)[1] == gate_first
    assert second == "Key"
    assert env_of(key) == {"HAS_KEY": "${{ secrets.ANTHROPIC_API_KEY != '' }}"}
    assert "          HAS_KEY: ${{ secrets.ANTHROPIC_API_KEY != '' }}\n" in REVIEW_TEXT
    assert run_of(key) == CALL.replace("range-gate", "range-key") + "\n"
    for name, block in range_steps():
        assert "\n        if: " not in block or name in ("Review", "Verdict"), name


def test_the_commit_is_checked_out_with_its_full_history_and_no_credential() -> None:
    block = range_step("Check out the commit with full history")
    lines = [line.strip() for line in block.splitlines()[1:]]
    assert lines[0].startswith("uses: actions/checkout@")
    assert lines[1:] == [
        "with:",
        "ref: ${{ github.sha }}",
        "fetch-depth: 0",
        "persist-credentials: false",
    ]


def test_the_script_and_uv_are_set_up_as_for_the_review_of_a_pull_request() -> None:
    """The commit's checkout empties the workspace, so the script is checked out again after it,
    where Prepare's check of a link reads it."""
    review = dict(review_steps())
    for name in ("Check out the review script from xippios/.github", "Install uv"):
        assert range_step(name) == without_condition(review[name]), name


def test_prepare_checks_the_link_before_the_script_runs_from_there() -> None:
    block = range_step("Prepare the range material")
    assert "        id: prepare\n" in block
    assert "        working-directory: ${{ runner.temp }}\n" in block
    review = dict(review_steps())["Prepare the review material"]
    check = run_of(review).split("set --\n", 1)[0]
    assert check.startswith('if [ -L "$GITHUB_WORKSPACE/.sdk-gates" ]; then\n')
    script = run_of(block)
    assert script.startswith(check)
    assert script.index("fi\n") < script.index("uv run")
    assert env_of(block) == {
        "GH_TOKEN": "${{ github.token }}",
        "DOCUMENTS_READ_TOKEN": env_of(review)["DOCUMENTS_READ_TOKEN"],
        "REPO": "${{ github.repository }}",
        "COMMIT": "${{ github.sha }}",
        "MAIN": "origin/${{ github.event.repository.default_branch }}",
    }
    assert "range-prepare" in script
    assert '--repo "$REPO" --commit "$COMMIT" --workspace "$GITHUB_WORKSPACE" --main "$MAIN"' in (
        " ".join(script.replace("\\\n", " ").split())
    )


def test_review_is_the_review_step_of_a_pull_request_after_prepare() -> None:
    """The same call with the same key and the same judge: the material says what it judges."""
    block = range_step("Review")
    review = dict(review_steps())["Review"]
    assert without_condition(block) == without_condition(review)
    assert "        if: steps.prepare.outputs.review == 'true'\n" in block + "\n"


def test_the_verdict_runs_after_any_review_that_prepare_let_run() -> None:
    block = range_step("Verdict")
    assert "        if: ${{ !cancelled() && steps.prepare.outputs.review == 'true' }}\n" in (
        block + "\n"
    )
    assert env_of(block) == {
        "RESULT_FILE": "${{ runner.temp }}/verdict.json",
        "GH_TOKEN": "${{ github.token }}",
        "REPO": "${{ github.repository }}",
        "PR": "${{ needs.gate.outputs.pr }}",
        "COMMIT": "${{ github.sha }}",
    }
    assert run_of(block) == CALL.replace("range-gate", "range-verdict") + "\n"


def test_no_run_line_holds_an_expression() -> None:
    for name, block in range_steps():
        if "\n        run: " in "\n" + block:
            assert "${{" not in run_of(block), name


# --- the steps' own scripts --------------------------------------------------------------

UV = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$(dirname "$0")/uv-calls"\n'
UV += 'while [ "$#" -gt 0 ] && [ "$1" != python ]; do shift; done\nshift\n'
UV += f'exec "{sys.executable}" "$@"\n'


def job_env(tmp_path: Path, answers: dict) -> dict[str, str]:
    """The environment a step of the job runs in, as the runner gives it: the workspace with the
    script's checkout in `.sdk-gates`, the runner's temporary directory, the files of the step's
    outputs and summary, emptied, and the stub `gh` and `uv` first on the path."""
    workspace = tmp_path / "workspace"
    script = workspace / ".sdk-gates" / "scripts" / "conventions.py"
    if not script.exists():
        script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, script)
    temp = tmp_path / "temp"
    temp.mkdir(exist_ok=True)
    bin_dir = stub_gh.install(tmp_path / "bin", answers)
    (bin_dir / "uv").write_text(UV)
    (bin_dir / "uv").chmod(0o755)
    (tmp_path / "summary.md").write_text("")
    (tmp_path / "output.txt").write_text("")
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GIT_", "GITHUB_")) and name != "ANTHROPIC_API_KEY"
    }
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_WORKSPACE": str(workspace),
            "RUNNER_TEMP": str(temp),
            "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


def run_step(name: str, env: dict[str, str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run the `run:` script of the step `name` as the runner's default shell runs it."""
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", run_of(range_step(name))],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(("has_key", "code"), [("true", 0), ("false", 1)])
def test_the_key_step_fails_with_the_sentence_of_the_gate_where_the_key_is_empty(
    tmp_path: Path, has_key: str, code: int
) -> None:
    env = {**job_env(tmp_path, {}), "HAS_KEY": has_key}
    done = run_step("Key", env, env["GITHUB_WORKSPACE"])
    assert done.returncode == code
    said = [EMPTY_KEY] if code else []
    assert (tmp_path / "summary.md").read_text().splitlines() == said
    assert done.stdout.splitlines() == said
    assert stub_gh.calls(tmp_path / "bin") == []


def git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    env = {name: value for name, value in env.items() if name not in ("GIT_DIR", "GIT_WORK_TREE")}
    done = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env
    )
    return done.stdout.strip()


def checkout(workspace: Path) -> str:
    """The caller's commit checked out in the workspace: a release tag, then a step's change."""
    workspace.mkdir(parents=True, exist_ok=True)
    git(workspace, "init", "-q", "-b", "main")
    readme = "# sdk-usda-psd\n\n## Documents\n\n- sdk-usda-psd: [docs/c.md](docs/c.md) — it.\n"
    (workspace / "README.md").write_text(readme)
    (workspace / "docs").mkdir()
    (workspace / "docs" / "c.md").write_text("# conventions\n")
    git(workspace, "add", "README.md", "docs")
    git(workspace, "commit", "-q", "-m", "feat: the first commit")
    git(workspace, "tag", "v0.1.0")
    (workspace / "mod.py").write_text("VALUE = 1\n")
    git(workspace, "add", "mod.py")
    git(workspace, "commit", "-q", "-m", "feat: the last step")
    return git(workspace, "rev-parse", "HEAD")


def prepare_env(tmp_path: Path) -> tuple[dict[str, str], str]:
    env = job_env(tmp_path, {})
    sha = checkout(Path(env["GITHUB_WORKSPACE"]))
    env.update({"GH_TOKEN": "dummy", "DOCUMENTS_READ_TOKEN": "", "REPO": REPO, "COMMIT": sha})
    env["MAIN"] = "main"
    return env, sha


def test_a_commit_that_carries_the_last_release_tag_skips_the_review_and_the_verdict(
    tmp_path: Path,
) -> None:
    """Prepare writes `review=false` with its sentence, so Review and Verdict do not run: no
    model call, no comment, and the job passes (finding 2 of the review of .github#137)."""
    env, sha = prepare_env(tmp_path)
    git(Path(env["GITHUB_WORKSPACE"]), "tag", "v0.2.0", sha)
    done = run_step("Prepare the range material", env, env["RUNNER_TEMP"])
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "output.txt").read_text() == "review=false\n"
    notice = (
        f"conventions: the commit {sha} carries the last release tag v0.2.0; no commit came "
        "after it, so the range holds nothing to judge"
    )
    assert (tmp_path / "summary.md").read_text().splitlines() == [notice]
    context = {"steps": {"prepare": {"outputs": {"review": "false"}}}}
    review = re.search(r"^        if: (.*)$", range_step("Review"), re.M).group(1)
    assert not holds(review, context)
    verdict = re.search(r"^        if: (.*)$", range_step("Verdict"), re.M).group(1)
    assert verdict == "${{ !cancelled() && " + review + " }}"
    assert stub_gh.calls(tmp_path / "bin") == []


def test_prepare_writes_the_range_material_by_the_steps_own_script(tmp_path: Path) -> None:
    env, sha = prepare_env(tmp_path)
    done = run_step("Prepare the range material", env, env["RUNNER_TEMP"])
    assert done.returncode == 0, done.stdout + done.stderr
    meta = json.loads((Path(env["GITHUB_WORKSPACE"]) / ".review" / "meta.json").read_text())
    assert (meta["kind"], meta["repo"], meta["commit"], meta["tag"]) == (
        "range",
        REPO,
        sha,
        "v0.1.0",
    )
    assert (tmp_path / "output.txt").read_text() == "review=true\n"
    uv_calls = (tmp_path / "bin" / "uv-calls").read_text().splitlines()
    assert len(uv_calls) == 1
    assert "--no-project --no-config --exclude-newer 2026-10-29T00:00:00Z" in uv_calls[0]
    assert " range-prepare --repo " in uv_calls[0]


def test_prepare_judges_a_merge_without_a_release_tag_against_its_first_parent(
    tmp_path: Path,
) -> None:
    """Where no release tag is reachable, the step's own script judges the merged pull
    request's whole change and none of the history before it (the answer of .github#138)."""
    env = job_env(tmp_path, {})
    workspace = Path(env["GITHUB_WORKSPACE"])
    git(workspace, "init", "-q", "-b", "main")
    readme = "# sdk-usda-psd\n\n## Documents\n\n- sdk-usda-psd: [docs/c.md](docs/c.md) — it.\n"
    (workspace / "README.md").write_text(readme)
    (workspace / "docs").mkdir()
    (workspace / "docs" / "c.md").write_text("# conventions\n")
    git(workspace, "add", "README.md", "docs")
    git(workspace, "commit", "-q", "-m", "feat: the first commit")
    first = git(workspace, "rev-parse", "HEAD")
    git(workspace, "checkout", "-q", "-b", "step")
    (workspace / "mod.py").write_text("VALUE = 1\n")
    git(workspace, "add", "mod.py")
    git(workspace, "commit", "-q", "-m", "feat: the step")
    step = git(workspace, "rev-parse", "HEAD")
    git(workspace, "checkout", "-q", "main")
    (workspace / "other.py").write_text("OTHER = 1\n")
    git(workspace, "add", "other.py")
    git(workspace, "commit", "-q", "-m", "feat: a merge before it")
    parent = git(workspace, "rev-parse", "HEAD")
    git(workspace, "merge", "-q", "--no-ff", "-m", "Merge pull request #7", "step")
    merge = git(workspace, "rev-parse", "HEAD")
    env.update({"GH_TOKEN": "dummy", "DOCUMENTS_READ_TOKEN": "", "REPO": REPO, "COMMIT": merge})
    env["MAIN"] = "main"
    done = run_step("Prepare the range material", env, env["RUNNER_TEMP"])
    assert done.returncode == 0, done.stdout + done.stderr
    review = workspace / ".review"
    meta = json.loads((review / "meta.json").read_text())
    assert (meta["commit"], meta["since"], meta["tag"]) == (merge, parent, None)
    diff = (review / "diff.patch").read_text()
    assert "+VALUE = 1" in diff
    assert "OTHER" not in diff
    log = (review / "log.txt").read_text()
    assert f"commit {merge}\n" in log
    assert f"commit {step}\n" in log
    assert first not in log
    assert parent not in log
    assert (tmp_path / "summary.md").read_text().splitlines()[0] == (
        "conventions: no release tag is reachable from the commit; the review judges what "
        f"{merge} changed against its first parent {parent}"
    )
    assert (tmp_path / "output.txt").read_text() == "review=true\n"


def test_prepare_refuses_a_link_in_place_of_the_scripts_checkout(tmp_path: Path) -> None:
    env, _sha = prepare_env(tmp_path)
    gates = Path(env["GITHUB_WORKSPACE"]) / ".sdk-gates"
    shutil.move(gates, tmp_path / "elsewhere")
    gates.symlink_to(tmp_path / "elsewhere")
    done = run_step("Prepare the range material", env, env["RUNNER_TEMP"])
    assert done.returncode == 1
    line = "conventions: .sdk-gates is a link; the review cannot run"
    assert (tmp_path / "summary.md").read_text() == line + "\n"
    assert not (tmp_path / "bin" / "uv-calls").exists()


def test_the_verdict_posts_the_comment_by_the_steps_own_script(tmp_path: Path) -> None:
    env = job_env(
        tmp_path, {"view": {"title": "0.5.0 Step 4: Last", "labels": []}, "comments": [[]]}
    )
    result = Path(env["RUNNER_TEMP"]) / "verdict.json"
    data = {
        "verdict": "ready",
        "findings": [],
        "range": {"kind": "range", "commit": COMMIT, "since": "a" * 40, "tag": "v0.1.0"},
        "documents": ["sdk-usda-psd: docs/c.md"],
    }
    result.write_text(json.dumps(data))
    env.update(
        {"RESULT_FILE": str(result), "GH_TOKEN": "dummy", "REPO": REPO, "PR": "7", "COMMIT": COMMIT}
    )
    done = run_step("Verdict", env, env["GITHUB_WORKSPACE"])
    assert done.returncode == 0, done.stdout + done.stderr
    writes = stub_gh.written(tmp_path / "bin")
    assert [(write["method"], write["endpoint"]) for write in writes] == [
        ("POST", f"repos/{REPO}/issues/7/comments")
    ]
    body = writes[0]["input"]["body"]
    assert body.startswith("<!-- style: reviews/conventions -->\n**Approved.** No findings at ")
    assert body == (tmp_path / "summary.md").read_text()
    assert body.endswith(f'<!-- conventions-run: {{"head":"{COMMIT}","findings":[]}} -->\n')


# --- the README --------------------------------------------------------------------------


def entry() -> str:
    """The README's entry of the workflow, as one line."""
    text = README.split("**`.github/workflows/conventions-range.yml`**", 1)[1]
    return " ".join(text.split("\n- **", 1)[0].split())


def test_the_readme_lists_the_workflow_and_its_two_check_contexts() -> None:
    """The table names `range / range` first, the check the entry opens with, then the gate's."""
    assert "**`.github/workflows/conventions-range.yml`**" in README
    rows = re.findall(r"^\| `conventions-range\.yml` \| `range` \| `([^`]+)` \|$", README, re.M)
    assert rows == ["range / range", "range / gate"]
    flat = entry()
    assert "check `range / range`" in flat
    assert "check `range / gate`" in flat
    assert "reports as skipped" in flat
    permissions = "`contents: read`, `pull-requests: write`, `checks: read`, `issues: read`"
    assert f"Permissions: {permissions}" in flat
    assert "judges no range yet" not in flat
    assert "a false condition" not in flat


def test_the_readme_says_what_the_gate_decides_case_by_case() -> None:
    flat = entry()
    for text in (
        "**The gate** (`conventions.py range-gate`)",
        "on the runner's `python3` with `-I`",
        "`contents: read`, `pull-requests: read` and `issues: read`",
        "times out after 5 minutes",
        "`run`",
        "`pr`",
        "**A dispatch** always lets the range be judged",
        "A push to a branch other than the default branch is not judged",
        "the merged one among the commit's pull requests whose merge commit is the pushed commit",
        "labeled `release` or titled `<version> Release`",
        "a pull request without a milestone",
        "a step left holds the range, and the sentence names it",
        "whose type is `step`, compared without case",
        "carries no type is a step where its title has the step form",
        "seconds after the merge",
        "never by a search, whose index can lag just after a merge",
        "An error fails closed",
        "names the call and the class of the error",
        # The time limits (finding 2 of the review of .github#130).
        (
            "A call of `gh` gets at most 30 seconds and all of them together 240 seconds, so "
            "the gate ends with its line a minute before the job's timeout"
        ),
        # The order of the outputs (finding 3 of the review of .github#130).
        "`run` is written last, after the sentence and `pr`",
    ):
        assert text in flat, text
    # No record that a reader of this public repository cannot open.
    assert "coordinate-core#" not in flat
    assert "coordinate-core/issues" not in flat


def test_the_readme_says_what_the_range_judges_and_what_its_check_means() -> None:
    flat = entry()
    for text in (
        "**The range** (`conventions.py range-prepare`)",
        "the commits since the last release tag (`v*`) reachable from the commit of the event",
        (
            "with the judge, the effort, the turn cap and the documents of the review of a "
            "release pull request, read as that review reads them"
        ),
        "It judges no pull request: its material holds no description and no checks",
        "names no release version",
        "the version's bump, the changelog's section and the tag",
        # The answer of .github#138: no release tag reachable.
        (
            "Where no release tag is reachable from the commit, the run judges what the commit "
            "of the event changed against its first parent, which for a merge is the merged pull "
            "request's whole change"
        ),
        "A commit with no parent is judged on its own change, and the job summary says which",
        "links no documents passes with its notice and makes no model call",
        # A commit that carries the last release tag (finding 2 of the review of .github#137).
        (
            "A commit that carries the last release tag holds no commit after it: the job passes "
            "with its notice, makes no model call and posts no comment"
        ),
        # What a run builds on (step 4 of .github 0.5.0).
        "**What a run builds on**",
        "**The check** `range / range`",
        "passed: the range was judged `ready`",
        # The two cases in which a passed check stands for no judged range (finding 3).
        "a README that links no documents, or a commit that carries the last release tag",
        "So a check that passed stands for a judged range but in those two cases",
        "failed:",
        "skipped:",
        "**The verdict** (`conventions.py range-verdict`)",
        "the job summary",
        "hidden last line",
        "the gate's `pr`",
        "A second run on the same commit rewrites that comment",
        "a release pull request, which only a dispatch can bring",
        "**The key**",
        "before the commit is checked out",
        "the failover",
        "**The job**",
        "`contents: read`, `pull-requests: write` and `checks: read`",
        "45 minutes",
        "a newer run cancels the older one",
        "**What a caller needs**",
        "`ANTHROPIC_API_KEY`",
    ):
        assert text in flat, text
    assert "coordinate-core#" not in flat
    assert "coordinate-core/issues" not in flat
    for old in (
        "every commit from the repository's first",
        "from the repository's first commit",
        "Each run judges the whole range as a first run, whatever comment stands on the pull",
    ):
        assert old not in flat, old


def test_the_readme_runs_the_review_of_a_commit_locally() -> None:
    section = README.split("\n## Running the review locally\n", 1)[1].split("\n## ", 1)[0]
    assert "dry-run --repo xippios/<repo> --pr <n>" in section
    assert "dry-run --repo xippios/<repo> --commit <sha>" in section
    flat = " ".join(section.split())
    assert "`--commit <sha>` in place of `--pr <n>`" in flat
    assert "as the job `range` does" in flat
    assert (
        "from the last release tag reachable from it, or, where none is, what the commit changed "
        "against its first parent"
    ) in flat
    assert "first commit" not in flat
