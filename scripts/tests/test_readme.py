"""README.md and ci.yml describe this repository by its name, `.github`, never as `sdk-gates`,
its name from 2026-10-27 to the rename back, and name the organization's rulesets as they are
(.github#10).

The repository is public, so neither the README nor the header comment of a workflow states a
known gap of the gates, a bypass of a ruleset or a cost (coordinate-core#630, coordinate-core#631,
.github#44)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
WORKFLOWS = ROOT / ".github" / "workflows"
CI = (WORKFLOWS / "ci.yml").read_text()
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
    assert "uses: xippios/.github/.github/workflows/merge-class.yml@main" in README
    assert "uses: xippios/.github/.github/workflows/conventions.yml@main" in README
    assert "uses: xippios/sdk-gates/.github/workflows/" not in README


def test_the_rulesets_named_are_the_organizations() -> None:
    for name in ("GitHub Main", "XIPPIOS SDK Main", "XIPPIOS SDK Tags"):
        assert f"`{name}`" in README
    for old in ("sdk-main-protection", "sdk-merge-class"):
        assert old not in README
        assert old not in CI


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
    flat = " ".join(header(name).split()).lower()
    assert flat, name
    for text in UNSTATED:
        assert text not in flat, text
