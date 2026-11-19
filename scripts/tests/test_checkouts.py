"""conventions.yml checks this repository out by its name, `xippios/.github` (gap .github#16): the
`sdk-gates` redirect is gone since 2026-11-03. The checkout directory keeps its name, `.sdk-gates`,
which the review script and its tests know."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_the_review_checks_the_repository_out_by_its_name() -> None:
    text = (WORKFLOWS / "conventions.yml").read_text()
    assert "repository: xippios/.github" in text
    assert "xippios/sdk-gates" not in text
