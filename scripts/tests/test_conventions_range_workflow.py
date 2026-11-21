"""`conventions-range.yml`, the conventions review of a range of commits (.github#96), is callable
with its final secrets and permissions before it has its logic (step 1 of .github 0.5.0,
.github#102): a trigger file that calls it on a push to `main` or on a dispatch grants from the
start what it asks for, since a caller that grants less than a called workflow asks for fails at
its start. Its one job, `range`, never starts until it has its logic, so its check `range / range`
reports as skipped. The file carries no comment (.github#111)."""

from pathlib import Path

from workflow_yaml import parse

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PATH = WORKFLOWS / "conventions-range.yml"
SECRETS = ("ANTHROPIC_API_KEY", "DOCUMENTS_READ_TOKEN")


def workflow() -> dict:
    """The workflow as the strict reader reads it, which refuses any comment."""
    return parse(PATH.read_text())


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
    assert workflow()["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "checks": "read",
        "issues": "read",
    }


def test_its_one_job_range_never_starts_so_its_check_reports_as_skipped() -> None:
    jobs = workflow()["jobs"]
    assert list(jobs) == ["range"]
    job = jobs["range"]
    # The job's name joins the caller's job id `range` to the context `range / range`.
    assert job["name"] == "range"
    # A job whose condition is false never starts, and its check reports as skipped. actionlint
    # refuses the constant `false` in a condition, and `fromJSON('false')` is false all the same.
    assert job["if"] == "fromJSON('false')"
    assert job["runs-on"] == "ubuntu-latest"
    assert "uses" not in job
    assert "secrets." not in PATH.read_text()


def test_the_file_carries_no_comment() -> None:
    assert "#" not in PATH.read_text()


def test_the_readme_lists_the_workflow_and_its_check_context() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "**`.github/workflows/conventions-range.yml`**" in readme
    assert "| `conventions-range.yml` | `range` | `range / range` |" in readme
    entry = readme.split("**`.github/workflows/conventions-range.yml`**", 1)[1]
    flat = " ".join(entry.split("\n- **", 1)[0].split())
    assert "check `range / range`" in flat
    assert "reports as skipped" in flat
    permissions = "`contents: read`, `pull-requests: write`, `checks: read`, `issues: read`"
    assert f"Permissions: {permissions}" in flat
