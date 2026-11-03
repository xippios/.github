"""CODEOWNERS of this repository: every path is the human's, so the organisation ruleset's
code-owner review (gate coordinate#9) is the human's approval on every pull request here (C50).
Read as text, like the workflows."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / ".github" / "CODEOWNERS").read_text()
RULES = [line.split() for line in TEXT.splitlines() if line.strip() and not line.startswith("#")]


def test_one_rule_names_an_owner_for_every_path() -> None:
    assert len(RULES) == 1
    pattern, *owners = RULES[0]
    assert pattern == "*"
    assert owners
    assert all(owner.startswith("@") for owner in owners)


def test_no_machine_user_owns_a_path() -> None:
    _pattern, *owners = RULES[0]
    # the [AI] accounts' logins end in -ai; their approval is a recommendation, never an ownership
    assert all(not owner.endswith("-ai") for owner in owners)
