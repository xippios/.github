"""auto.yml: the auto gate of the coordinate workspaces (coordinate-core 0.4.0, C50). A reusable
workflow that approves a run's pull request, on a `run/*` branch of the repository and opened by the
platform account of the organisation variable, with the coordinate App's token, and nothing else.
Read as text: the workflows of this repository are checked by actionlint, not parsed here."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / ".github" / "workflows" / "auto.yml").read_text()


def test_auto_is_a_reusable_workflow_named_auto() -> None:
    assert "name: Auto\n" in TEXT
    assert "workflow_call:" in TEXT and "pull_request:" not in TEXT  # the caller's gates.yml runs on pull_request


def test_only_a_runs_pull_request_by_the_platform_from_this_repository_is_approved() -> None:
    condition = TEXT.split("if: >-", 1)[1].split("steps:", 1)[0]
    assert "startsWith(github.event.pull_request.head.ref, 'run/')" in condition
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition  # no forks
    assert "github.event.pull_request.user.login == vars.COORDINATE_PLATFORM_LOGIN" in condition
    assert "vars.COORDINATE_PLATFORM_LOGIN != ''" in condition  # unset variable: nothing is approved
    assert not re.search(r"\b[a-z]-[a-z]+-ai\b", TEXT)  # no login in the file; the variable carries it


def test_the_approval_is_the_apps_and_only_an_approval() -> None:
    assert "actions/create-github-app-token@" in TEXT and "# v2." in TEXT  # pinned to a sha, the version in a comment
    assert "vars.COORDINATE_APP_ID" in TEXT and "secrets.COORDINATE_APP_PEM" in TEXT
    assert "-f event=APPROVE" in TEXT and 'commit_id="$HEAD"' in TEXT
    assert "REQUEST_CHANGES" not in TEXT and "COMMENT" not in TEXT and "pr merge" not in TEXT


def test_the_workflows_own_permissions_are_read_only() -> None:
    permissions = TEXT.split("permissions:", 1)[1].split("jobs:", 1)[0]
    assert "contents: read" in permissions and "pull-requests: read" in permissions and "write" not in permissions
    assert "timeout-minutes:" in TEXT
