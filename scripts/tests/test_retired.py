"""The retired parts of this repository stay gone.

The `auto` gate is retired (coordinate-core 0.5.2 step 5, coordinate-core#133, .github#26). A
run's pull request is reviewed by the reviewer like any other, and the template's `gates.yml` no
longer calls `auto.yml`, so the workflow, its tests and its README entry leave this repository.

The forms generator is retired (.github#33). From coordinate-core 0.6.4 the coordinate
workspace's adoption run writes the issue forms and the PR template from the style of the core's
release (coordinate-core#371), so nothing runs `scripts/forms.py`, and it leaves with its tests.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
README = (ROOT / "README.md").read_text()


def test_the_auto_gate_is_gone() -> None:
    assert not (WORKFLOWS / "auto.yml").exists()
    assert not (ROOT / "scripts" / "tests" / "test_auto.py").exists()


def test_no_workflow_calls_or_names_the_auto_gate() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        text = workflow.read_text()
        assert "auto.yml" not in text, workflow.name
        assert "COORDINATE_PLATFORM_LOGIN" not in text, workflow.name


def test_the_readme_lists_the_workflows_that_remain() -> None:
    assert "workflows/auto.yml" not in README
    assert "COORDINATE_PLATFORM_LOGIN" not in README
    for name in ("merge-class.yml", "conventions.yml", "spelling.yml", "ci.yml"):
        assert f"**`.github/workflows/{name}`**" in README, name


def test_the_forms_generator_is_gone() -> None:
    assert not (ROOT / "scripts" / "forms.py").exists()
    assert not (ROOT / "scripts" / "tests" / "test_forms.py").exists()


def test_no_workflow_runs_the_forms_generator() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        assert "forms.py" not in workflow.read_text(), workflow.name


def test_the_readme_says_who_writes_the_forms() -> None:
    assert "forms.py" not in README
    section = README.split("\n## The forms\n", 1)[1].split("\n## ", 1)[0]
    assert "adoption run" in section
    assert "coordinate-core#371" in section
    assert "`config.yml` stays by hand" in section
