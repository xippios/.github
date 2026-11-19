"""The review left this repository's own pull requests (C58, .github#12): conventions.yml runs as a
called job only, and nothing here claims that every pull request is human by a rule of a gate."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def triggers(name: str) -> str:
    text = (WORKFLOWS / name).read_text()
    return text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]


def test_the_review_runs_as_a_called_job_only() -> None:
    block = triggers("conventions.yml")
    assert "workflow_call:" in block
    assert "pull_request:" not in block


def test_nothing_claims_rule_3_for_this_repository() -> None:
    assert "rule 3" not in (ROOT / ".github" / "CODEOWNERS").read_text()
    readme = (ROOT / "README.md").read_text()
    assert "waits for the human" not in readme.split("## The workflows", 1)[0]
    assert "caller-wiring proof" not in readme
    assert "reviews itself" not in readme
