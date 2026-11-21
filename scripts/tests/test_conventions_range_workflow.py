"""`conventions-range.yml`, the conventions review of a range of commits (.github#96), is callable
with its final secrets and permissions before it has its logic (step 1 of .github 0.5.0,
.github#102): a trigger file that calls it on a push to `main` or on a dispatch grants from the
start what it asks for, since a caller that grants less than a called workflow asks for fails at
its start. Its first job, `gate`, knows the merge that completes a package (step 3 of
.github 0.5.0, .github#99): it runs on a push and on a dispatch alone, with permissions narrower
than the workflow's, and calls `conventions.py range-gate` once from the script's checkout, the
values in its `env:` block. The job `range` never starts until step 3.1 gives it its logic, so its
check `range / range` reports as skipped. The file carries no comment but the version after a
pinned action (.github#111)."""

import re
from pathlib import Path

import pytest
from expressions import runs
from workflow_yaml import parse

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PATH = WORKFLOWS / "conventions-range.yml"
TEXT = PATH.read_text()
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
# The job `range` as step 1 gave it, which step 3.1 replaces.
RANGE = """\
  range:
    name: range
    if: fromJSON('false')
    runs-on: ubuntu-latest
    steps:
      - run: exit 0
"""


def workflow() -> dict:
    """The workflow as the strict reader reads it, which refuses any comment: the version after
    a pinned action is taken off first."""
    return parse(VERSION.sub(r"\1", TEXT))


def gate() -> dict:
    return workflow()["jobs"]["gate"]


def test_the_workflow_is_titled_conventions_range() -> None:
    assert workflow()["name"] == "Conventions range"


def test_it_is_callable_alone_with_the_two_secrets_of_the_review_both_optional() -> None:
    on = workflow()["on"]
    assert list(on) == ["workflow_call"]
    assert on["workflow_call"] == {"secrets": {name: {"required": "false"} for name in SECRETS}}
    # The same two as the review of a pull request, so a trigger file passes both to each.
    central = (WORKFLOWS / "conventions.yml").read_text()
    central = central.split("  workflow_call:\n    secrets:\n", 1)[1].split("\npermissions:", 1)[0]
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
    assert list(workflow()["jobs"]) == ["gate", "range"]


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
    assert "secrets." not in TEXT


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
    assert first_step(TEXT) == first_step((WORKFLOWS / "conventions.yml").read_text())
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
    assert "uv " not in TEXT


def test_the_workflow_holds_no_inline_code() -> None:
    """No `run:` feeds Python a here-document or a `-c` program, and no block of script."""
    assert "<<" not in TEXT
    assert re.search(r"python3?( -[A-Za-z]+)* -( |$)", TEXT, re.M) is None
    assert re.search(r"python3?( -[A-Za-z]+)* -c\b", TEXT) is None
    assert "run: |" not in TEXT


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


# --- the job range -----------------------------------------------------------------------


def test_the_range_stays_the_stub_that_never_starts_so_its_check_reports_as_skipped() -> None:
    """Step 3.1 gives it its logic; until then a job whose condition is false never starts, and
    its check reports as skipped. actionlint refuses the constant `false` in a condition, and
    `fromJSON('false')` is false all the same."""
    assert TEXT.endswith("\n\n" + RANGE)
    job = workflow()["jobs"]["range"]
    # The job's name joins the caller's job id `range` to the context `range / range`.
    assert job["name"] == "range"
    assert job["if"] == "fromJSON('false')"
    assert "needs" not in job


def test_the_file_carries_no_comment_but_the_version_of_a_pinned_action() -> None:
    assert "#" not in VERSION.sub(r"\1", TEXT)


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
    ):
        assert text in flat, text
    # No record that a reader of this public repository cannot open.
    assert "coordinate-core#" not in flat
    assert "coordinate-core/issues" not in flat
