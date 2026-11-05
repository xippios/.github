"""auto.yml: the auto gate of the coordinate workspaces (coordinate-core 0.4.0, C50). A reusable
workflow that approves a run's pull request, on a `run/*` branch of the repository and opened by the
platform account of the organization variable, with the coordinate App's token, and nothing else.
Read as text: the workflows of this repository are checked by actionlint, not parsed here."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / ".github" / "workflows" / "auto.yml").read_text()


def test_auto_is_a_reusable_workflow_named_auto() -> None:
    assert "name: Auto\n" in TEXT
    assert "workflow_call:" in TEXT
    assert "pull_request:" not in TEXT  # the caller's gates.yml runs on pull_request


def test_only_a_runs_pull_request_by_the_platform_from_this_repository_is_approved() -> None:
    condition = TEXT.split("if: >-", 1)[1].split("steps:", 1)[0]
    assert "startsWith(github.event.pull_request.head.ref, 'run/')" in condition
    # no forks
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
    assert "github.event.pull_request.user.login == vars.COORDINATE_PLATFORM_LOGIN" in condition
    # an unset variable: nothing is approved
    assert "vars.COORDINATE_PLATFORM_LOGIN != ''" in condition
    # no login in the file; the variable carries it
    assert not re.search(r"\b[a-z]-[a-z]+-ai\b", TEXT)


def test_the_approval_is_the_apps_and_only_an_approval() -> None:
    # pinned to a sha, the version in a comment
    assert "actions/create-github-app-token@" in TEXT
    assert "# v2." in TEXT
    assert "vars.COORDINATE_APP_ID" in TEXT
    assert "secrets.COORDINATE_APP_PEM" in TEXT
    assert "-f event=APPROVE" in TEXT
    assert 'commit_id="$HEAD"' in TEXT
    assert "REQUEST_CHANGES" not in TEXT
    assert "COMMENT" not in TEXT
    assert "pr merge" not in TEXT


def test_the_workflows_own_permissions_are_read_only() -> None:
    permissions = TEXT.split("permissions:", 1)[1].split("jobs:", 1)[0]
    assert "contents: read" in permissions
    assert "pull-requests" not in permissions  # nothing uses the workflow token for PRs
    assert "write" not in permissions
    assert "timeout-minutes:" in TEXT


def test_the_secret_is_declared_and_the_app_token_narrowed() -> None:
    triggers = TEXT.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "COORDINATE_APP_PEM:" in triggers
    assert "required: true" in triggers
    assert "permission-pull-requests: write" in TEXT
    assert "secrets: inherit" not in TEXT  # the caller passes the one secret by name (C65)
