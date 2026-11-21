"""No workflow file of this repository carries a comment but one kind, the version after a pinned
action, `uses: <action>@<40 hex> # <version>`, with or without the letter `v`, as the action's own
tags write it (step 2.1 of .github 0.5.0, .github#111). What a comment said stands in the README.
The test reads every file under `.github/workflows/` and knows no list of them, so a new file is
held too.

A line that opens with `#` after its indent is a comment, in a block scalar too. Elsewhere a line is
read by the rule of its language. Outside a block scalar it is YAML's: a `#` opens a comment where
white space or the line's start stands before it and no quoted value holds it, and a quote opens a
quoted value only where a value starts, never inside plain text (finding 2 of the review of
.github#124). Inside a block scalar, the script of a `run:` block or a folded condition, it is the
shell's, since the shell runs the text and YAML reads no comment there: a `#` opens a comment where
it starts a word outside the shell's quotes, which open anywhere and run on over the lines of the
block."""

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


# A key whose value is a block scalar, `|` or `>` with its indicators, and what may follow it.
BLOCK = re.compile(r" *(?:- )?([A-Za-z0-9_.-]+): *[|>][-+0-9]*(?: +#.*)?")
# What ends a word for the shell, so that a `#` after it starts one.
WORD_END = " \t;&|()<>"


def closing(line: str, start: int) -> int:
    """Where the quoted value that opens at ``start`` of ``line`` ends, past its closing quote:
    `''` stands for a quote in single quotes, a backslash escapes in double quotes. A value that
    the line does not close runs to the line's end."""
    quote = line[start]
    position = start + 1
    while position < len(line):
        char = line[position]
        if quote == '"' and char == "\\":
            position += 2
            continue
        if char == quote:
            if quote == "'" and line.startswith("''", position):
                position += 2
                continue
            return position + 1
        position += 1
    return len(line)


def yaml_comment(line: str) -> bool:
    """Whether ``line``, read as YAML, carries a comment: a `#` after white space or at the line's
    start that no quoted value holds. A quote opens a quoted value only where a value starts: at
    the line's start, after `- `, after `: `, and in a flow collection after `[`, `{` or `,`."""
    position = len(line) - len(line.lstrip(" "))
    start = True
    depth = 0
    while position < len(line):
        char = line[position]
        if start and char in "'\"":
            position, start = closing(line, position), False
        elif char == "#" and (position == 0 or line[position - 1] in " \t"):
            return True
        elif char in " \t":
            position += 1
        elif start and line.startswith("- ", position):
            position += 2
        elif char == ":" and line[position + 1 : position + 2] in ("", " "):
            position, start = position + 1, True
        elif char in "[{" and (start or depth):
            position, depth, start = position + 1, depth + 1, True
        elif char == "," and depth:
            position, start = position + 1, True
        elif char in "]}" and depth:
            position, depth, start = position + 1, depth - 1, False
        else:
            position, start = position + 1, False
    return False


def shell_comment(line: str, quote: str | None) -> tuple[bool, str | None]:
    """Whether ``line`` of a script carries a comment, a `#` that starts a word outside the
    shell's quotes, and the quote still open at its end. ``quote`` is the one the line before
    left open."""
    escaped = False
    previous = " "
    for char in line:
        if escaped:
            escaped = False
        elif quote == "'":
            if char == "'":
                quote = None
        elif char == "\\":
            escaped = True
        elif quote == '"':
            if char == '"':
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and previous in WORD_END:
            return True, quote
        previous = char
    return False, quote


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def comment_lines(text: str) -> list[int]:
    """The numbers of the lines of ``text`` that carry a comment of the kind no file keeps: a line
    that opens with `#`, and else a comment by YAML's rule outside a block scalar, or by the
    shell's inside one, but for the version after a pinned action."""
    found = []
    # The column a line of the open block scalar stands right of, and the shell's open quote.
    block: int | None = None
    quote: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if block is not None and (not line.strip() or indent(line) > block):
            comment, quote = shell_comment(line, quote)
            if line.lstrip().startswith("#") or comment:
                found.append(number)
            continue
        block, quote = None, None
        if line.lstrip().startswith("#") or (yaml_comment(line) and not PINNED.fullmatch(line)):
            found.append(number)
        opened = BLOCK.fullmatch(line)
        if opened:
            block = opened.start(1)
    return found


PIN = "3d3c42e5aac5ba805825da76410c181273ba90b1"
# Each case a text of a workflow file and the lines of it that carry a comment.
CASES = {
    "a comment line": ("# The header.\nname: CI\n", [1]),
    "a comment line above a step": ("jobs:\n  a:\n    # A step.\n    runs-on: x\n", [3]),
    "a comment line in a run block": ("steps:\n  - run: |\n      # A step.\n      echo a\n", [3]),
    "a version after an action not pinned": (
        "      - uses: actions/checkout@main # v7.0.1\n",
        [1],
    ),
    "a pin with no version": (f"      - uses: actions/checkout@{PIN} # pinned\n", [1]),
    "a pin with more than its version": (
        f"      - uses: actions/checkout@{PIN} # v7.0.1 new\n",
        [1],
    ),
    "a comment after a value": ("    timeout-minutes: 5 # minutes\n", [1]),
    "a comment after a block indicator": ("    run: | # the script\n      echo a\n", [1]),
    "a comment in a run block's script": ("steps:\n  - run: |\n      echo done # the end\n", [3]),
    "a comment after plain text with an apostrophe": (
        "        description: the site's key # a comment\n",
        [1],
    ),
    "a comment after plain text with a double quote": (
        '        description: a 12" disk # a comment\n',
        [1],
    ),
    "a comment after a quote inside a one-line run": ('    run: echo "a # b"\n', [1]),
    "a comment after a single-quoted value": ("    name: 'a # b' # a comment\n", [1]),
    "a comment after a double-quoted value": ('    name: "a # b" # a comment\n', [1]),
    "YAML's rule again after a block": (
        "steps:\n  - run: |\n      echo '#'\n  - name: a # b\n",
        [4],
    ),
    "the version after a pinned action": (f"      - uses: actions/checkout@{PIN} # v7.0.1\n", []),
    "the version without the letter v": (
        "        uses: shivammathur/setup-php@eb7c497e18156a6bbabfef1d3a82760b9eda3962 # 2.40.0\n",
        [],
    ),
    "a hash in a single-quoted value": ("    name: 'a # b'\n", []),
    "a hash in a double-quoted value": ('    name: "a # b"\n', []),
    "a hash in a quoted item of a flow sequence": ("    items: ['a # b', c]\n", []),
    "a hash with no white space before it": ("    name: a#b\n", []),
    "the fragment of a URL": ("    url: https://example.com/page#part\n", []),
    "a quoted condition": ("    if: vars.WORKFLOW_SPELLING != 'off'\n", []),
    "a hash inside a word of the script": (
        'steps:\n  - run: |\n      if [ "${#paths[@]}" -eq 0 ]; then\n',
        [],
    ),
    "the shell's count of arguments": ("steps:\n  - run: |\n      echo $#\n", []),
    "a hash in the shell's quotes": (
        "steps:\n  - run: |\n      echo '#' \"it's # here\"\n",
        [],
    ),
    "a hash in escaped quotes": (
        'steps:\n  - run: |\n      export X="{\\"a\\": \\"#\\"}"\n',
        [],
    ),
    "a hash in a quote over two lines of a script": (
        "steps:\n  - run: |\n      echo 'a\n      b # c'\n",
        [],
    ),
}


@pytest.mark.parametrize(("text", "lines"), CASES.values(), ids=list(CASES))
def test_the_reader_finds_each_comment_and_no_other(text: str, lines: list[int]) -> None:
    assert comment_lines(text) == lines


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
    assert comment_lines(path.read_text()) == []


@pytest.mark.parametrize("path", FILES, ids=[path.name for path in FILES])
def test_every_action_is_pinned_with_its_version(path: Path) -> None:
    """A `uses:` of another repository's action names a commit and its version; a reusable
    workflow of this repository is called by its path."""
    for line in path.read_text().splitlines():
        if re.match(r" *(?:- )?uses: ", line) and "uses: ./" not in line:
            assert PINNED.fullmatch(line), line
