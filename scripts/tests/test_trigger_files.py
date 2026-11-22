"""The README shows the trigger file of each check as a repository holds it (step 1 of
.github 0.5.0, .github#102, .github#107): a small workflow of the repository's own, named as the
central workflow it calls, that names the events, the permissions and the secrets and calls this
repository at `main`. Each block is free of comments (.github#111), reads in the subset of YAML
that `workflow_yaml` reads, calls a workflow file of this repository, grants exactly what that
workflow asks for, passes by name only secrets it declares and the inputs it requires, and keeps
the check context of the table. The trigger file `conventions.yml` carries one condition on each
job, the name of the event and the switch `WORKFLOW_CONVENTIONS`, so a pull request calls the
review of the pull request alone, any other event the range alone, and `off` neither. Its jobs
pass the key alone, as a repository that reads no private document takes the file, and the prose
beside it shows the line that a workspace with private documents adds, filled from its own secret
(step 6.2 of .github 0.5.0, .github#149). The callers of today, a root's `gates.yml` and a
source's `organization.yml`, call as before."""

import re
from pathlib import Path

import pytest
from expressions import runs
from workflow_yaml import UnreadError, parse

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
README = (ROOT / "README.md").read_text()
WIRING = README.split("\n## Wiring and check contexts\n", 1)[1].split("\n## ", 1)[0]
NAMES = ["conventions.yml", "spelling.yml", "adr-index.yml"]
FOUR = ["opened", "synchronize", "reopened", "edited"]
THREE = FOUR[:3]
USES = re.compile(r"xippios/\.github/\.github/workflows/([a-z-]+\.yml)@main")
# The condition of each job of the trigger file `conventions.yml`.
CONDITIONS = {
    "conventions": "github.event_name == 'pull_request' && vars.WORKFLOW_CONVENTIONS != 'off'",
    "range": "github.event_name != 'pull_request' && vars.WORKFLOW_CONVENTIONS != 'off'",
}
LEVELS = {"read": 1, "write": 2}


def blocks() -> list[tuple[str, str]]:
    """Each trigger file of the README in its order: the file name its path names, its text."""
    return re.findall(r"`\.github/workflows/([a-z-]+\.yml)`:\n\n```yaml\n(.*?)```", WIRING, re.S)


def trigger_file(name: str) -> dict:
    return parse(dict(blocks())[name])


def central(name: str) -> dict:
    """The title, the events and the permissions of the workflow `name` of this repository,
    read before its jobs and without its comment lines."""
    head = (WORKFLOWS / name).read_text().split("\njobs:\n", 1)[0]
    return parse("\n".join(line for line in head.splitlines() if not line.startswith("#")))


def job_names(name: str) -> list[str]:
    """The names of the jobs of the workflow `name`, the second half of their check contexts."""
    jobs = (WORKFLOWS / name).read_text().split("\njobs:\n", 1)[1]
    return re.findall(r"^  [a-z-]+:\n    name: ([a-z-]+)$", jobs, re.M)


# --- the reader --------------------------------------------------------------------------


def test_the_reader_reads_the_subset() -> None:
    text = "a:\n  b: [x, y]\n  c:\n  d:\n    - e: f\n      g: h\n    - e: i\nj: ${{ k.l }}\n"
    assert parse(text) == {
        "a": {"b": ["x", "y"], "c": None, "d": [{"e": "f", "g": "h"}, {"e": "i"}]},
        "j": "${{ k.l }}",
    }


@pytest.mark.parametrize(
    "text",
    [
        "a: b # a comment\n",
        "# a comment\na: b\n",
        "a:\n\tb: c\n",
        "a: b\na: c\n",
        "a:\n   b: c\n",
        "a: b\n  c: d\n",
        "a: 'b'\n",
        "a: |\n  b\n",
        "a: [b, 'c']\n",
        "a: b: c\n",
        "a:  b\n",
        "a: b:\n",
        "- a: b\n",
        "a:\n- b: c\n",
    ],
)
def test_the_reader_refuses_what_it_does_not_know(text: str) -> None:
    with pytest.raises(UnreadError):
        parse(text)


# --- the trigger files -------------------------------------------------------------------


def test_the_readme_shows_the_three_trigger_files() -> None:
    assert [name for name, _text in blocks()] == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_each_trigger_file_reads_and_carries_no_comment(name: str) -> None:
    text = dict(blocks())[name]
    assert "#" not in text
    assert set(parse(text)) == {"name", "on", "permissions", "jobs"}


@pytest.mark.parametrize("name", NAMES)
def test_each_trigger_file_bears_the_title_of_the_workflow_it_is_named_after(name: str) -> None:
    assert trigger_file(name)["name"] == central(name)["name"]
    titles = {
        "conventions.yml": "Conventions",
        "spelling.yml": "Spelling",
        "adr-index.yml": "ADR index",
    }
    assert trigger_file(name)["name"] == titles[name]


@pytest.mark.parametrize("name", NAMES)
def test_each_trigger_file_runs_on_the_types_of_a_pull_request_its_check_reads(name: str) -> None:
    """An edit starts the review only, since the review judges the description: the trigger file
    `conventions.yml` runs on the four types, and `spelling.yml` and `adr-index.yml`, which read
    no description, on the first three (finding 1 of the review of .github#115)."""
    on = trigger_file(name)["on"]
    if name == "conventions.yml":
        assert on == {
            "pull_request": {"types": FOUR},
            "push": {"branches": ["main"]},
            "workflow_dispatch": None,
        }
    else:
        assert on == {"pull_request": {"types": THREE}}


def test_the_readme_says_that_an_edit_starts_the_review_only() -> None:
    flat = " ".join(WIRING.split())
    assert "An edit starts the review only" in flat
    assert (
        "The trigger files `spelling.yml` and `adr-index.yml` run on a pull request's opening, "
        "push and reopening, the types `opened`, `synchronize` and `reopened`, since an edit "
        "starts the review only" in flat
    )
    assert "`spelling.yml` and `adr-index.yml` run on a pull request's four types" not in flat


@pytest.mark.parametrize("name", NAMES)
def test_each_job_calls_a_workflow_of_this_repository_at_main(name: str) -> None:
    called = []
    for job in trigger_file(name)["jobs"].values():
        match = USES.fullmatch(job["uses"])
        assert match, job["uses"]
        assert (WORKFLOWS / match.group(1)).is_file(), match.group(1)
        called.append(match.group(1))
    assert name in called
    expected = ["conventions.yml", "conventions-range.yml"] if name == "conventions.yml" else [name]
    assert called == expected


@pytest.mark.parametrize("name", NAMES)
def test_each_job_grants_exactly_what_its_workflow_asks_for(name: str) -> None:
    """A job's own permissions replace the file's, and a caller that grants less than the called
    workflow asks for fails at its start."""
    workflow = trigger_file(name)
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        asked = central(USES.fullmatch(job["uses"]).group(1))["permissions"]
        granted = job.get("permissions", workflow["permissions"])
        assert granted == asked, job["uses"]
        assert all(level in LEVELS for level in granted.values())


@pytest.mark.parametrize("name", NAMES)
def test_each_job_passes_declared_secrets_by_name_and_the_required_inputs(name: str) -> None:
    for job in trigger_file(name)["jobs"].values():
        call = central(USES.fullmatch(job["uses"]).group(1))["on"]["workflow_call"] or {}
        declared = call.get("secrets") or {}
        passed = job.get("secrets", {})
        assert passed != "inherit"
        assert set(passed) <= set(declared), job["uses"]
        assert {key for key, spec in declared.items() if spec["required"] == "true"} <= set(passed)
        for secret, value in passed.items():
            assert value == f"${{{{ secrets.{secret} }}}}"
        inputs = call.get("inputs") or {}
        given = job.get("with", {})
        assert set(given) <= set(inputs)
        assert {key for key, spec in inputs.items() if spec["required"] == "true"} <= set(given)


def test_the_conventions_trigger_file_passes_the_key_alone_to_each_job() -> None:
    """The sample is the file as a repository that reads no private document takes it: the read
    token's line left out reads as none (.github#149)."""
    for job in trigger_file("conventions.yml")["jobs"].values():
        assert job["secrets"] == {"ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"}


@pytest.mark.parametrize("name", ["conventions.yml", "conventions-range.yml"])
def test_both_workflows_keep_the_read_token_as_an_optional_secret_of_their_call(name: str) -> None:
    """The name is the workflows' own: a trigger file fills it from whichever secret its workspace
    keeps, or leaves it out, and no workflow changes for it (.github#149)."""
    secrets = central(name)["on"]["workflow_call"]["secrets"]
    assert secrets == {
        "ANTHROPIC_API_KEY": {"required": "false"},
        "DOCUMENTS_READ_TOKEN": {"required": "false"},
    }


@pytest.mark.parametrize("name", NAMES)
def test_each_job_keeps_the_check_context_of_the_table(name: str) -> None:
    """Each job of the called workflow is a check context of its own: `conventions-range.yml`
    reports `range / gate` and `range / range` (step 3 of .github 0.5.0)."""
    for job_id, job in trigger_file(name)["jobs"].items():
        called = USES.fullmatch(job["uses"]).group(1)
        for job_name in job_names(called):
            row = f"| `{called}` | `{job_id}` | `{job_id} / {job_name}` |"
            assert row in WIRING, row
    assert job_names("conventions-range.yml") == ["gate", "range"]
    if name != "conventions.yml":
        assert list(trigger_file(name)["jobs"]) == [name.removesuffix(".yml")]


def test_each_job_of_the_conventions_trigger_file_carries_one_condition() -> None:
    jobs = trigger_file("conventions.yml")["jobs"]
    assert list(jobs) == ["conventions", "range"]
    for job_id, job in jobs.items():
        assert job["if"] == CONDITIONS[job_id]


@pytest.mark.parametrize("name", ["spelling.yml", "adr-index.yml"])
def test_the_spelling_and_adr_index_trigger_files_carry_no_condition(name: str) -> None:
    for job in trigger_file(name)["jobs"].values():
        assert "if" not in job


@pytest.mark.parametrize("event", ["pull_request", "push", "workflow_dispatch"])
@pytest.mark.parametrize("value", ["", "on", "off", "Off", "OFF", "anything"])
def test_one_job_calls_its_workflow_on_each_event_and_none_on_off(event: str, value: str) -> None:
    jobs = trigger_file("conventions.yml")["jobs"]
    variables = {"WORKFLOW_CONVENTIONS": value} if value else {}
    called = {job_id for job_id, job in jobs.items() if runs(job["if"], event, variables)}
    if value.lower() == "off":
        assert called == set()
    else:
        assert called == ({"conventions"} if event == "pull_request" else {"range"})


# --- the prose ---------------------------------------------------------------------------


def test_the_readme_says_what_a_trigger_file_switches_and_what_goes_first() -> None:
    flat = " ".join(WIRING.split())
    assert "The presence of a trigger file switches its check on." in flat
    assert "Where a repository requires a check, the requirement goes before the file does." in flat


def test_the_readme_says_where_the_read_token_is_needed_in_prose() -> None:
    flat = " ".join(WIRING.split())
    assert (
        "`DOCUMENTS_READ_TOKEN`, which the review needs only in a private repository whose README "
        "lists a private repository's document" in flat
    )
    assert "the empty string" not in flat
    assert "A trigger file passes both" not in flat


def test_the_readme_says_that_a_trigger_file_fills_the_read_token_from_its_own_secret() -> None:
    """The caller's secret is its workspace's, as the web workspace's `WEB_READ_TOKEN`, and a
    repository that reads no private document leaves the line out (.github#149)."""
    flat = " ".join(WIRING.split())
    assert (
        "A trigger file fills `DOCUMENTS_READ_TOKEN` from the secret that its workspace keeps for "
        "reading its private repositories, as the web workspace does from `WEB_READ_TOKEN`, and a "
        "repository that reads no private document leaves the line out, which reads as none" in flat
    )
    # Beside the sample: its jobs pass the key alone, and the one line a workspace with private
    # documents adds, the web workspace's as the example.
    sample = WIRING.split("### The trigger files", 1)[1].split("```yaml\n", 1)[0]
    sample = " ".join(sample.split())
    assert (
        "Both jobs pass `ANTHROPIC_API_KEY` by name and leave the read token's line out, as a "
        "repository that reads no private document takes the file" in sample
    )
    # Every trigger file `conventions.yml` of today passes a read token, so the README counts
    # none (finding 2 of the review of .github#150).
    assert "most repositories" not in " ".join(README.split())
    assert "`DOCUMENTS_READ_TOKEN: ${{ secrets.WEB_READ_TOKEN }}`" in sample
    assert "secrets.DOCUMENTS_READ_TOKEN" not in README


def test_the_readme_keeps_the_callers_of_today() -> None:
    flat = " ".join(WIRING.split())
    assert (
        "A `gates.yml` and an `organization.yml` call the workflows as before until their "
        "repository takes the trigger files with an adoption" in flat
    )
    assert "The jobs of a `gates.yml` or an `organization.yml` carry no `if:`" in flat
    assert "on `off` neither job calls its workflow" in flat
