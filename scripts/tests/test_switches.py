"""Each workflow gets its switch (step 1.1 of .github 0.5.0, .github#111): a variable
`WORKFLOW_<NAME>` with the values `on` and `off` switches a workflow whose file exists. GitHub reads
the calling repository's variable over the organization's, a called workflow reads its caller's,
and the workflow is on where neither sets one. `spelling.yml` and `adr-index.yml` skip their one
job on `off`, their condition written as the trigger file `conventions.yml` writes its switch, so
only `off`, in any case, switches a workflow off, and their checks report as skipped and passing.
The review carries its switch `WORKFLOW_CONVENTIONS` in the trigger file alone, so
`conventions.yml` and `conventions-range.yml` read no switch of their own, and `site-tests.yml` and
`ci.yml` get none in this step. The README says which variable switches each of the three entries,
in one sentence of one form, and that this repository's own `ci` counts a `spelling` job that did
not run as not passed."""

import re
from pathlib import Path

import pytest
from expressions import runs

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
README = (ROOT / "README.md").read_text()
WIRING = README.split("\n## Wiring and check contexts\n", 1)[1].split("\n## ", 1)[0]
# The workflows that carry their switch in their job's condition, each with its variable.
SWITCHED = {"spelling.yml": "WORKFLOW_SPELLING", "adr-index.yml": "WORKFLOW_ADR_INDEX"}
# The variables of the caller that each workflow reads.
READ = {
    "adr-index.yml": {"WORKFLOW_ADR_INDEX"},
    "ci.yml": set(),
    "conventions-range.yml": set(),
    "conventions.yml": {"WORKFLOW_CONVENTIONS_MODE"},
    "site-tests.yml": set(),
    "spelling.yml": {"WORKFLOW_SPELLING"},
}
# The entries of the README that name their switch, each with its variable.
ENTRIES = {
    "spelling.yml": "WORKFLOW_SPELLING",
    "conventions.yml": "WORKFLOW_CONVENTIONS",
    "adr-index.yml": "WORKFLOW_ADR_INDEX",
}
VALUES = ["", "on", "On", "off", "Off", "OFF", "anything"]


def conditions(name: str) -> list[tuple[str, str]]:
    """Each job of the workflow `name` whose `if:` follows its name, with that condition."""
    jobs = (WORKFLOWS / name).read_text().split("\njobs:\n", 1)[1]
    return re.findall(r"^  ([a-z-]+):\n    name: [a-z-]+\n    if: (.+)$", jobs, re.M)


def entry(name: str) -> str:
    """The README's entry of the workflow `name`, as one line."""
    section = README.split(f"- **`.github/workflows/{name}`**", 1)[1]
    return " ".join(section.split("\n- **`.github/workflows/", 1)[0].split())


def switch_section() -> str:
    """The README's paragraph on the switch, under the wiring, as one line."""
    return " ".join(WIRING.split("\n### The switch\n", 1)[1].split("\n### ", 1)[0].split())


# --- the switches ------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SWITCHED))
def test_the_job_carries_its_switch_as_the_trigger_file_writes_one(name: str) -> None:
    """The one job under the name of its check, with the condition of the trigger file's form."""
    assert conditions(name) == [(name.removesuffix(".yml"), f"vars.{SWITCHED[name]} != 'off'")]


@pytest.mark.parametrize("name", sorted(SWITCHED))
@pytest.mark.parametrize("value", VALUES)
def test_only_off_in_any_case_skips_the_job(name: str, value: str) -> None:
    """With no value, `on` or any other value the job runs; `off`, compared without case, skips
    it, so its check reports as skipped and passing."""
    [(_job, condition)] = conditions(name)
    variables = {SWITCHED[name]: value} if value else {}
    assert runs(condition, "pull_request", variables) == (value.lower() != "off")


@pytest.mark.parametrize("name", sorted(SWITCHED))
@pytest.mark.parametrize(
    ("repository", "organization", "on"),
    [
        (None, None, True),
        ("off", None, False),
        (None, "off", False),
        ("on", "off", True),
        ("off", "on", False),
    ],
)
def test_the_repositorys_value_counts_before_the_organizations(
    name: str, repository: str | None, organization: str | None, on: bool
) -> None:
    """`vars` is the caller's: the repository's variable where it sets one, else the
    organization's, else none."""
    [(_job, condition)] = conditions(name)
    levels = [level for level in (organization, repository) if level is not None]
    variables = {SWITCHED[name]: levels[-1]} if levels else {}
    assert runs(condition, "pull_request", variables) == on


def test_each_workflow_reads_only_its_own_variables() -> None:
    """`conventions.yml` reads the mode alone, since the review's switch is the trigger file's,
    and `conventions-range.yml`, `site-tests.yml` and `ci.yml` read no switch."""
    assert set(READ) == {path.name for path in WORKFLOWS.glob("*.yml")}
    for name, variables in READ.items():
        read = set(re.findall(r"\bvars\.([A-Za-z0-9_]+)", (WORKFLOWS / name).read_text()))
        assert read == variables, name


# --- the README --------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "variable"), ENTRIES.items())
def test_each_entry_names_its_switch_in_one_sentence_of_one_form(name: str, variable: str) -> None:
    text = entry(name)
    assert f"The variable `{variable}` switches it (the switch, under the wiring below)." in text
    assert text.count("switches it (the switch, under the wiring below).") == 1


def test_the_readme_lays_out_the_switch_under_the_wiring() -> None:
    text = switch_section()
    assert (
        "A variable `WORKFLOW_<NAME>` with the values `on` and `off` switches a workflow whose "
        "file exists" in text
    )
    assert "GitHub reads the calling repository's variable over the organization's" in text
    assert "a called workflow reads its caller's" in text
    assert "the workflow is on where neither sets one" in text
    off = "Only `off` switches it off, compared without case, and any other value leaves it on"
    assert off in text
    for name in sorted(SWITCHED):
        [(_job, condition)] = conditions(name)
        assert f"`{condition}`" in text, name
    assert "no runner starts and the check reports as skipped and passing" in text
    assert "`WORKFLOW_CONVENTIONS` in the trigger file `conventions.yml`" in text
    assert "`conventions / conventions` reports nothing" in text


def test_the_trigger_files_say_where_the_switch_of_the_other_two_is() -> None:
    flat = " ".join(WIRING.split())
    assert (
        "Each has its one job under the job id that keeps its check context and carries no "
        "condition, since the workflow it calls carries its switch (the switch, below)." in flat
    )


def test_the_readme_says_once_that_ci_counts_a_spelling_job_that_did_not_run_as_not_passed() -> (
    None
):
    """ci.yml fails `ci` on any result of the job `spelling` but success, so the switch
    `WORKFLOW_SPELLING` is for callers; ci.yml itself stays as it is."""
    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "if: ${{ needs.spelling.result != 'success' }}" in ci
    sentence = (
        "`ci` counts a `spelling` job that did not run as not passed, so the switch "
        "`WORKFLOW_SPELLING` is for callers."
    )
    assert sentence in entry("ci.yml")
    assert " ".join(README.split()).count("did not run as not passed") == 1
