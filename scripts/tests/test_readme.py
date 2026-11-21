"""README.md and ci.yml describe this repository by its name, `.github`, never as `sdk-gates`,
its name from 2026-10-27 to the rename back, and name the organization's rulesets as they are
(.github#10).

The repository is public, so neither the README nor the header comment of a workflow states a
known gap of the gates, a bypass of a ruleset or a cost (coordinate-core#630, coordinate-core#631,
.github#44). The README links no private repository: of the organization's repositories it links
this one alone and names the others in words (proof 1 of .github 0.3.0). It and the comment of
`.github/CODEOWNERS` name the human by role, in words, as the house style names a member
(.github#63); the rule line keeps the login, which is what GitHub reads."""

import re
from pathlib import Path

import pytest

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


def header(name: str) -> str:
    """The text of the comment that opens the workflow `name`, before its first key."""
    lines = []
    for line in (WORKFLOWS / name).read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            break
        lines.append(line.removeprefix("#"))
    return "\n".join(lines)


def test_the_readme_is_titled_by_the_repositorys_name() -> None:
    assert README.splitlines()[0] == "# xippios/.github"
    assert "Renamed from `xippios/.github`" not in README


def test_the_caller_example_names_the_repository_as_it_is() -> None:
    assert "uses: xippios/.github/.github/workflows/spelling.yml@main" in README
    assert "uses: xippios/.github/.github/workflows/conventions.yml@main" in README
    assert "uses: xippios/sdk-gates/.github/workflows/" not in README


def test_the_readme_names_the_ruleset_of_this_repository_alone() -> None:
    """The README keeps the ruleset of this repository, `GitHub Main`, and what a caller needs;
    the rulesets of the other repositories stay in the core's private spec (ADR-0011 of
    coordinate-core, finding 1 of the review of .github#76)."""
    section = README.split("\n## Rulesets\n", 1)[1].split("\n## ", 1)[0]
    assert "**`GitHub Main`**" in section
    for name in ("Coordinate ", "XIPPIOS "):
        assert name not in README
    assert "sdk-main-protection" not in README
    assert "sdk-main-protection" not in CI


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
    flat = " ".join(README.split())
    assert "Every pull request here waits for the human" in flat
    assert "`.github/CODEOWNERS` names the human for every path" in flat
    assert "the human's code-owner approval" in flat


def test_ci_describes_this_repository() -> None:
    assert CI.startswith("# CI of xippios/.github.")
    # the proof job fails on a protected path, not on every pull request (the sdk-gates rule)
    assert "is human (rule 3)" not in CI
    assert "`GitHub Main`" in CI


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


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_no_workflow_header_states_a_known_gap_a_bypass_or_a_cost(name: str) -> None:
    """A workflow file may open without a comment, since it carries none but the version after a
    pinned action (.github#111), as `conventions-range.yml` does from its start."""
    flat = " ".join(header(name).split()).lower()
    for text in UNSTATED:
        assert text not in flat, text
