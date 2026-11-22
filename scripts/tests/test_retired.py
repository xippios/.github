"""The retired parts of this repository stay gone.

The `auto` gate is retired (coordinate-core 0.5.2 step 5, coordinate-core#133, .github#26). A
run's pull request is reviewed by the reviewer like any other, and the template's `gates.yml` no
longer calls `auto.yml`, so the workflow, its tests and its README entry leave this repository.

The forms generator is retired (.github#33). From coordinate-core 0.6.4 the coordinate
workspace's adoption run writes the issue forms and the PR template from the style of the core's
release (coordinate-core#371), so nothing runs `scripts/forms.py`, and it leaves with its tests.

The merge-class gate is retired (.github#31, step 1 of .github 0.3.0). Its callers name the
workflow no more, so `merge-class.yml` leaves with `scripts/merge_class.py`, its tests and the
names that only it used, `FAMILY_REPOSITORIES` and `FAMILY_TEST_FILES`. The README describes
what stays, without the families, the merge classes and the classifier's local run.

The old name of the review's mode is retired (step 1.1 of .github 0.5.0, .github#111). The mode
is the variable `WORKFLOW_CONVENTIONS_MODE` with the values `release` and `all`, and the switch
`WORKFLOW_CONVENTIONS` of the trigger file replaces the value `off`, so the old name, which no
repository and no organization sets, is read nowhere: not in a workflow, the script or the README.

Two leftovers are retired (step 2.1 of .github 0.5.0). A release PR is told by its label `release`
or by the title `<version> Release` alone, so the older title form `release: <version>` is read
nowhere: not by the job's condition, not by the script's pattern and not in a notice, a docstring
or the README. And the check's comment is known by the
marker of the style alone, so a comment that opens with the marker from before it is no comment of
the check: neither read as the run before nor edited in place.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
README = (ROOT / "README.md").read_text()
# What only the merge-class gate named.
MERGE_CLASS = ("merge-class", "merge_class", "FAMILY_REPOSITORIES", "FAMILY_TEST_FILES")
# The old name of the review's mode, named here alone.
OLD_MODE = "CONVENTIONS_REVIEW"
# The old title form of a release PR as a text, the job's condition and the script's pattern wrote
# it, and the comment marker from before the markers of the style.
OLD_TITLE = ("release: <version>", "'release: '", "release: v?")
OLD_MARKER = "<!-- conventions -->"


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
    listed = set(re.findall(r"\*\*`\.github/workflows/([a-z-]+\.yml)`\*\*", README))
    assert listed == {workflow.name for workflow in WORKFLOWS.glob("*.yml")}
    for name in ("spelling.yml", "conventions.yml", "site-tests.yml", "adr-index.yml", "ci.yml"):
        assert name in listed, name


def test_the_merge_class_gate_is_gone() -> None:
    assert not (WORKFLOWS / "merge-class.yml").exists()
    assert not (ROOT / "scripts" / "merge_class.py").exists()
    assert not (ROOT / "scripts" / "tests" / "test_merge_class.py").exists()


def test_nothing_names_the_merge_class_gate_or_its_family_names() -> None:
    files = [ROOT / "README.md", ROOT / "ruff.toml", *sorted((ROOT / ".github").rglob("*"))]
    files += sorted((ROOT / "scripts").rglob("*.py"))
    this = Path(__file__).resolve()
    for path in files:
        if not path.is_file() or path.resolve() == this:
            continue
        text = path.read_text()
        for name in MERGE_CLASS:
            assert name not in text, f"{path.relative_to(ROOT)} names {name}"


def test_the_readme_describes_no_family_and_no_merge_class() -> None:
    """The core's own documents hold the families and the merge classes from coordinate-core
    0.7.5 on; the README keeps what a caller of the remaining workflows needs."""
    for heading in ("## Merge classes", "## Running the classifier locally"):
        assert heading not in README
    flat = " ".join(README.split()).lower()
    assert "famil" not in flat
    assert "classifier" not in flat
    assert "gates_caller" not in flat


def test_nothing_reads_the_old_name_of_the_mode() -> None:
    files = [ROOT / "README.md", *sorted(WORKFLOWS.glob("*.yml"))]
    files += sorted((ROOT / "scripts").rglob("*.py"))
    this = Path(__file__).resolve()
    named = [str(path.relative_to(ROOT)) for path in files if path.resolve() != this]
    assert [name for name in named if OLD_MODE in (ROOT / name).read_text()] == []


def test_nothing_reads_the_old_title_form_or_the_old_marker() -> None:
    files = [ROOT / "README.md", ROOT / "scripts" / "conventions.py"]
    files += sorted(path for path in WORKFLOWS.iterdir() if path.is_file())
    for path in files:
        text = path.read_text()
        for old in (*OLD_TITLE, OLD_MARKER):
            assert old not in text, f"{path.relative_to(ROOT)} names {old}"


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
    assert "https://github.com/xippios/.github/issues/33" in section
    assert "`config.yml` stays by hand" in section
