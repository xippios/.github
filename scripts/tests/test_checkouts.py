"""The old workflows check this repository out by its name, `xippios/.github` (gap .github#16): the
`sdk-gates` redirect is gone since 2026-11-03. The checkout directory keeps its name, `.sdk-gates`,
which the review script and its tests know."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_the_old_workflows_check_the_repository_out_by_its_name() -> None:
    for name in ("merge-class.yml", "family-review.yml"):
        text = (WORKFLOWS / name).read_text()
        assert "repository: xippios/.github" in text
        assert "xippios/sdk-gates" not in text
