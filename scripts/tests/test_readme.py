"""README.md and ci.yml describe this repository by its name, `.github`, never as `sdk-gates`,
its name from 2026-10-27 to the rename back, and name the organization's rulesets as they are
(.github#10)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()


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
