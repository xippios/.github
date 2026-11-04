"""The review of the sdk family is the conventions review (C57): workflow `conventions.yml`, check
`conventions`, script `scripts/conventions.py`. The sdk callers switch to it with the migration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
OLD = ("family-review", "family_review")


def test_the_workflow_is_conventions_yml() -> None:
    assert (WORKFLOWS / "conventions.yml").is_file()
    assert not (WORKFLOWS / "family-review.yml").exists()
    assert (ROOT / "scripts" / "conventions.py").is_file()
    assert not (ROOT / "scripts" / "family_review.py").exists()


def test_the_check_is_named_conventions() -> None:
    text = (WORKFLOWS / "conventions.yml").read_text()
    jobs = text.split("\njobs:\n", 1)[1]
    assert jobs.startswith("  conventions:\n    name: conventions\n")


def test_nothing_here_names_the_old_review() -> None:
    files = [ROOT / "README.md", ROOT / ".github" / "actionlint.yaml"]
    files += sorted(WORKFLOWS.glob("*.yml")) + sorted((ROOT / "scripts").glob("*.py"))
    for path in files:
        text = path.read_text()
        for old in OLD:
            assert old not in text, f"{path.relative_to(ROOT)} names {old}"
