"""The evaluator of `expressions.py` reads a condition as GitHub does in the subset it knows, and
refuses what it does not know, so a test of a workflow's condition evaluates the condition the
file holds, not a model of it (step 2.1 of .github 0.5.0)."""

import pytest
from expressions import OutsideError, holds, runs

EVENT = {
    "event_name": "pull_request",
    "event": {
        "action": "opened",
        "pull_request": {
            "title": "0.7.4 Release",
            "labels": [{"name": "bug"}, {"name": "Release"}],
        },
    },
}


def context(**variables: str) -> dict:
    return {"github": EVENT, "vars": variables}


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("github.event_name == 'PULL_REQUEST'", True),
        ("github.event_name != 'pull_request'", False),
        ("vars.UNSET == ''", True),
        ("vars.MODE == 'all'", True),
        ("vars.MODE != 'ALL'", False),
        ("contains(github.event.pull_request.labels.*.name, 'release')", True),
        ("contains(github.event.pull_request.labels.*.name, 'feature')", False),
        ('contains(fromJSON(\'["opened", "edited"]\'), github.event.action)', True),
        ("contains(github.event.pull_request.title, 'release')", True),
        ("endsWith(github.event.pull_request.title, ' release')", True),
        ("startsWith(github.event.pull_request.title, 'release: ')", False),
        ("startsWith(github.event.pull_request.title, '0.7')", True),
        ("github.event_name == 'push' || vars.MODE == 'all'", True),
        ("github.event_name == 'push' && vars.MODE == 'all'", False),
        ("(github.event_name == 'push' || vars.MODE == 'all') && vars.UNSET != ''", False),
        ("github.event_name == 'push' || (vars.MODE == 'all' && vars.UNSET == '')", True),
        ("'it''s' == 'IT''S'", True),
        ("fromJSON('false')", False),
        ("fromJSON('[]')", True),
        ("vars.UNSET", False),
    ],
)
def test_the_evaluator_reads_the_subset_as_github_does(condition: str, expected: bool) -> None:
    assert holds(condition, context(MODE="All")) is expected


@pytest.mark.parametrize(
    "condition",
    [
        "github.event.number == '7'",
        "!cancelled()",
        "success()",
        "format('{0}', vars.MODE)",
        'vars.MODE == "all"',
        "vars.MODE === 'all'",
        "vars.MODE == 'all' &&",
        "(vars.MODE == 'all'",
        "fromJSON('1') == 'a'",
        "contains(vars.MODE)",
        "github.event.pull_request.labels.*.name.*.x == 'a'",
    ],
)
def test_the_evaluator_refuses_what_it_does_not_know(condition: str) -> None:
    with pytest.raises(OutsideError):
        holds(condition, context(MODE="all"))


def test_runs_gives_the_event_name_and_the_variables_alone() -> None:
    assert runs("github.event_name == 'push' && vars.X != 'off'", "push", {})
    assert not runs("github.event_name == 'push' && vars.X != 'off'", "push", {"X": "OFF"})
    with pytest.raises(OutsideError):
        runs("github.event.action == 'opened'", "pull_request", {})
