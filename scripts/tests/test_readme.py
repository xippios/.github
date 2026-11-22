"""README.md and ci.yml describe this repository by its name, `.github`, never as `sdk-gates`,
its name from 2026-10-27 to the rename back (.github#10).

The repository is public, so the README states nothing of protection: it names no ruleset, lists
none, and says of no repository which check it requires, whose approval a pull request waits for
or who merges (step 2.1 of .github 0.5.0). Neither the README nor a workflow states a known gap of
the gates, a bypass or a cost (coordinate-core#630, coordinate-core#631, .github#44). The README
links no private repository: of the organization's repositories it links this one alone and names
the others in words (proof 1 of .github 0.3.0). It and the comment of `.github/CODEOWNERS` name the
human by role, in words, as the house style names a member (.github#63); the rule line keeps the
login, which is what GitHub reads. That comment and the docstrings of two tests state nothing of
protection either (.github#125).

The entry of each workflow opens with one short paragraph of one form, its parts in one order:
what it checks, with its check, the events it runs on, what the calling file hands over, its
permissions, and the variable that switches it, or that none does (step 2.1 of .github 0.5.0)."""

import ast
import re
from pathlib import Path

import pytest
from workflow_yaml import parse

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
WORKFLOWS = ROOT / ".github" / "workflows"
CI = (WORKFLOWS / "ci.yml").read_text()
CODEOWNERS = (ROOT / ".github" / "CODEOWNERS").read_text()
# The paths a coordinate root's `gates.yml` gives `spelling.yml` at coordinate-core 0.7.6.
ROOT_PATHS = (
    "paths: rules docs/style docs/adr docs/adr.md docs/adr.json docs/reports README.md CLAUDE.md"
    " .claude workspace.toml labels.yml"
)
# The wording of a known gap, a bypass and a cost, as the README and the headers had it.
UNSTATED = ("known limits", "not a boundary", "net is open", "bypass", "cost", "billed", "credits")
# What the README said of protection until step 2.1 of .github 0.5.0: the rulesets by name and
# the command that lists them, the approvals and who gives them, the required checks and statuses,
# and who merges.
PROTECTION = (
    "ruleset",
    "approv",
    "code-owner",
    "code owner",
    "required check `",
    "required status",
    "waits for the human",
    "auto-merge",
)
RULESETS = ("GitHub Main", "Coordinate ", "XIPPIOS ", "sdk-main-protection")
FILES = sorted(path.name for path in WORKFLOWS.iterdir() if path.is_file())
# The events that the first paragraph of each entry names, and the variable that switches each.
EVENTS = {
    "adr-index.yml": "a pull request's opening, push and reopening",
    "ci.yml": "every pull request of this repository and on a push to `main`",
    "conventions-range.yml": "a push to `main` and on a dispatch",
    "conventions.yml": "a pull request's opening, push, reopening and edit",
    "site-tests.yml": "a pull request and on a push to `main`",
    "spelling.yml": "a pull request's opening, push and reopening",
}
SWITCHES = {
    "adr-index.yml": "WORKFLOW_ADR_INDEX",
    "ci.yml": None,
    "conventions-range.yml": "WORKFLOW_CONVENTIONS",
    "conventions.yml": "WORKFLOW_CONVENTIONS",
    "site-tests.yml": None,
    "spelling.yml": "WORKFLOW_SPELLING",
}


def first_paragraph(name: str) -> str:
    """The first paragraph of the README's entry of the workflow `name`, as one line."""
    entry = README.split(f"\n- **`.github/workflows/{name}`**", 1)[1]
    return " ".join(entry.split("\n\n", 1)[0].split())


def head(name: str) -> dict:
    """The title, the events and the permissions of the workflow `name`, before its jobs."""
    return parse((WORKFLOWS / name).read_text().split("\njobs:\n", 1)[0])


def handover(name: str) -> list[str]:
    """What the first paragraph says the calling file hands over, read from the workflow: each
    input and secret it declares, by name, or that it declares none."""
    on = head(name)["on"]
    if "workflow_call" not in on:
        return ["No file calls it"]
    call = on["workflow_call"] or {}
    inputs, secrets = call.get("inputs") or {}, call.get("secrets") or {}
    said = [f"`{key}`" for key in (*inputs, *secrets)]
    if not inputs:
        said.append("no input")
    if not secrets:
        said.append("no secret")
    return said


def check_context(name: str) -> str:
    """The check context of the workflow `name`, from the table of the wiring; `ci` for ci.yml."""
    found = re.search(rf"^\| `{re.escape(name)}` \| `[a-z-]+` \| `([^`]+)` \|$", README, re.M)
    return found.group(1) if found else "ci"


def test_the_readme_is_titled_by_the_repositorys_name() -> None:
    assert README.splitlines()[0] == "# xippios/.github"
    assert "Renamed from `xippios/.github`" not in README


def test_the_caller_example_names_the_repository_as_it_is() -> None:
    assert "uses: xippios/.github/.github/workflows/spelling.yml@main" in README
    assert "uses: xippios/.github/.github/workflows/conventions.yml@main" in README
    assert "uses: xippios/sdk-gates/.github/workflows/" not in README


def test_the_readme_states_nothing_of_protection() -> None:
    """No heading `Rulesets`, no ruleset by its name and no command that lists them, and no
    sentence on the approvals, the required checks or who merges, of this repository or any
    other. The mechanism stays in general words: a check's context, and that a required check
    leaves its requirement before its file goes."""
    assert "## Rulesets" not in README
    assert "/rulesets" not in README
    flat = " ".join(README.split())
    for text in PROTECTION:
        assert text not in flat.lower(), text
    for name in RULESETS:
        assert name not in README, name
        assert name not in CI, name
    assert "A context joins the caller's job id and the callee's job name" in flat
    assert "Where a repository requires a check, the requirement goes before the file does." in flat


def test_the_callers_paths_are_the_roots() -> None:
    """The caller of the spelling entry and the trigger file `spelling.yml` of the wiring give
    `spelling.yml` the paths of a coordinate root's caller, as the root's `gates.yml` names them
    at coordinate-core 0.7.6 (finding 2 of the review of .github#76)."""
    lines = [line.strip() for line in README.splitlines() if line.strip().startswith("paths: ")]
    assert lines == [ROOT_PATHS, ROOT_PATHS]


def test_the_readme_links_no_repository_of_the_organization_but_this_one() -> None:
    linked = set(re.findall(r"https://github\.com/xippios/([A-Za-z0-9._-]+)", README))
    assert linked <= {".github"}


def test_the_readme_and_codeowners_name_the_human_by_role() -> None:
    comment = "\n".join(line for line in CODEOWNERS.splitlines() if line.startswith("#"))
    rule = next(line.split() for line in CODEOWNERS.splitlines() if line.startswith("*"))
    logins = [owner.removeprefix("@") for owner in rule[1:]]
    for login in logins:
        assert login not in README
        assert login not in comment
    assert "the human's" in comment
    assert "kept by hand" in comment
    # Nothing of protection, as the README says none (.github#125).
    for text in PROTECTION:
        assert text not in comment.lower(), text
    for name in RULESETS:
        assert name not in comment, name


@pytest.mark.parametrize("name", ["test_codeowners.py", "test_retired.py"])
def test_the_docstrings_of_two_tests_state_nothing_of_protection(name: str) -> None:
    """The module docstrings that said how this repository is protected say it no more, as step
    2.1 of .github 0.5.0 reworded the README (.github#125)."""
    tree = ast.parse((ROOT / "scripts" / "tests" / name).read_text())
    flat = " ".join((ast.get_docstring(tree) or "").split()).lower()
    assert flat
    for text in PROTECTION:
        assert text not in flat, text
    assert "coordinate#9" not in flat


def test_ci_describes_this_repository() -> None:
    """ci.yml opens with its title, and the README's entry says what it runs."""
    assert CI.startswith("name: CI\n")
    # the proof job fails on a protected path, not on every pull request (the sdk-gates rule)
    assert "is human (rule 3)" not in CI
    assert "sdk-gates" not in CI


def test_the_readme_says_every_verdict_posts_the_conventions_comment() -> None:
    """Every verdict, `ready` included, goes to the one sticky comment (#36, #39)."""
    flat = " ".join(README.split())
    assert "every verdict, `ready` included, goes to one sticky PR comment" in flat
    assert "`not ready` fails the check and puts the findings in one sticky PR comment" not in flat


@pytest.mark.parametrize("text", UNSTATED)
def test_the_readme_states_no_known_gap_no_bypass_and_no_cost(text: str) -> None:
    assert text not in " ".join(README.split()).lower()


def test_the_readme_names_no_price() -> None:
    assert "USD" not in README


@pytest.mark.parametrize("name", FILES)
def test_no_workflow_states_a_known_gap_a_bypass_or_a_cost(name: str) -> None:
    flat = " ".join((WORKFLOWS / name).read_text().split()).lower()
    for text in UNSTATED:
        assert text not in flat, text


# --- the entries of the workflows --------------------------------------------------------


def test_each_workflow_file_has_its_entry_and_its_expectations() -> None:
    """A new workflow file fails here until its entry and what its paragraph names are added."""
    assert set(EVENTS) == set(SWITCHES) == set(FILES)
    listed = re.findall(r"^- \*\*`\.github/workflows/([a-z-]+\.yml)`\*\*", README, re.M)
    assert sorted(listed) == FILES


@pytest.mark.parametrize("name", FILES)
def test_each_entry_opens_with_one_paragraph_of_one_form(name: str) -> None:
    """What it checks, with its check, then the events, what the calling file hands over, the
    permissions and the switch, in that order and each once."""
    text = first_paragraph(name)
    parts = [f"check `{check_context(name)}`", f"It runs on {EVENTS[name]}"]
    parts.append("The calling file hands over" if handover(name)[0] != "No file calls it" else "")
    permissions = ", ".join(f"`{key}: {value}`" for key, value in head(name)["permissions"].items())
    parts.append(f"Permissions: {permissions}.")
    switch = SWITCHES[name]
    parts.append(
        f"The variable `{switch}` switches it (the switch, under the wiring below)."
        if switch
        else "No variable switches it."
    )
    positions = [text.find(part) for part in parts if part]
    assert -1 not in positions, (parts, text)
    assert positions == sorted(positions), text
    for part in handover(name):
        assert part in text, part
    assert text.count("Permissions:") == 1
    assert text.count("switches it") == 1
    assert len(text.split()) <= 110, len(text.split())


@pytest.mark.parametrize("name", FILES)
def test_the_rest_of_an_entry_repeats_neither_the_permissions_nor_the_switch(name: str) -> None:
    entry = README.split(f"\n- **`.github/workflows/{name}`**", 1)[1]
    entry = " ".join(entry.split("\n- **`.github/workflows/", 1)[0].split("\n## ", 1)[0].split())
    assert entry.count("Permissions:") == 1
    assert entry.count("switches it") == 1
