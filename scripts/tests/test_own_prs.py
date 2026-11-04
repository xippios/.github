"""The old workflows left this repository's own pull requests (C58, .github#12): merge-class.yml
and conventions.yml run as called jobs only, ci.yml carries no proof job, and nothing here
claims that every pull request is human by the classifier's rule 3."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def triggers(name: str) -> str:
    text = (WORKFLOWS / name).read_text()
    return text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]


def test_the_old_workflows_run_as_called_jobs_only() -> None:
    for name in ("merge-class.yml", "conventions.yml"):
        block = triggers(name)
        assert "workflow_call:" in block
        assert "pull_request:" not in block


def test_ci_carries_no_proof_job() -> None:
    assert "merge-class" not in (WORKFLOWS / "ci.yml").read_text()


def test_nothing_claims_rule_3_for_this_repository() -> None:
    assert "rule 3" not in (ROOT / ".github" / "CODEOWNERS").read_text()
    readme = (ROOT / "README.md").read_text()
    assert "waits for Johannes" not in readme.split("## The workflows", 1)[0]
    assert "caller-wiring proof" not in readme
    assert "reviews itself" not in readme
