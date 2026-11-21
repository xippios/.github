"""No workflow file of this repository carries a comment but one kind, the version after a pinned
action, `uses: <action>@<40 hex> # <version>`, with or without the letter `v`, as the action's own
tags write it (step 2.1 of .github 0.5.0, .github#111). What a comment said stands in the README.
The test reads every file under `.github/workflows/` and knows no list of them, so a new file is
held too, and it holds the lines of a `run:` block as it holds every other line."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
FILES = sorted(path for path in WORKFLOWS.iterdir() if path.is_file())
# The one comment a workflow file keeps: the version after an action pinned to a commit.
PINNED = re.compile(
    r" *(?:- )?uses: [A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40} # v?[0-9]+(?:\.[0-9]+)*"
)


def unquoted_hashes(line: str) -> list[int]:
    """The positions of each `#` of ``line`` outside a string in single or double quotes; a
    backslash escapes the next character inside double quotes, as in YAML and in the shell."""
    found = []
    quote = None
    escaped = False
    for position, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#":
            found.append(position)
    return found


def comment_of(line: str) -> str | None:
    """What makes ``line`` a comment of the kind no file keeps, or None where it is none."""
    if line.lstrip().startswith("#"):
        return "a comment line"
    if unquoted_hashes(line) and not PINNED.fullmatch(line):
        return "a comment after a value"
    return None


@pytest.mark.parametrize(
    "line",
    [
        "# The header.",
        "    # A comment above a step.",
        "          # A comment in a run: block.",
        "      - uses: actions/checkout@main # v7.0.1",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # pinned",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1 latest",
        "    timeout-minutes: 5 # minutes",
        "          echo done # the end",
    ],
)
def test_a_comment_is_found(line: str) -> None:
    assert comment_of(line) is not None


@pytest.mark.parametrize(
    "line",
    [
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
        "        uses: shivammathur/setup-php@eb7c497e18156a6bbabfef1d3a82760b9eda3962 # 2.40.0",
        '          if [ "${#paths[@]}" -eq 0 ]; then',
        "          echo '#' \"it's # here\"",
        '          export X="{\\"a\\": \\"#\\"}"',
        "    if: vars.WORKFLOW_SPELLING != 'off'",
    ],
)
def test_the_version_of_a_pinned_action_and_a_quoted_hash_are_no_comment(line: str) -> None:
    assert comment_of(line) is None


def test_the_test_reads_every_workflow_file() -> None:
    assert {path.name for path in FILES} >= {
        "adr-index.yml",
        "ci.yml",
        "conventions-range.yml",
        "conventions.yml",
        "site-tests.yml",
        "spelling.yml",
    }


@pytest.mark.parametrize("path", FILES, ids=[path.name for path in FILES])
def test_no_workflow_file_carries_a_comment(path: Path) -> None:
    found = [
        f"{number}: {kind}"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if (kind := comment_of(line)) is not None
    ]
    assert found == []


@pytest.mark.parametrize("path", FILES, ids=[path.name for path in FILES])
def test_every_action_is_pinned_with_its_version(path: Path) -> None:
    """A `uses:` of another repository's action names a commit and its version; a reusable
    workflow of this repository is called by its path."""
    for line in path.read_text().splitlines():
        if re.match(r" *(?:- )?uses: ", line) and "uses: ./" not in line:
            assert PINNED.fullmatch(line), line
