"""The issue forms and the PR template are generated from the style of the record (C73, C74,
.github#19): one field per section of the template, in its order and with its names; the type
set and no title prefix; no "Requested by" field."""

import re
from pathlib import Path

import forms
import pytest

ROOT = Path(__file__).resolve().parents[2]
KINDS = ("change", "gap", "package", "question", "gate", "note")

ISSUES = """\
# Issues

Intro.

## Row: change or gap

| | |
| --- | --- |
| Marker | `issues/row` |
| Written by | `coordinate issue new <repository> --kind change\\|gap --body-file <file>` |
| Title | a change in the imperative: `Refuse a thing`; a gap as a fact: `issue new doubles` |

Sections:

- `## What` (never left out): one or two sentences that state the whole change or gap. Add
  bullets for the parts when there are several.
- `## Why`: the reason, with its citations.
- `## Proof`: how one sees it done.
- `## Consumers`: who must act or adopt, one bullet each.

```markdown
<!-- style: issues/row -->
## What

An example.

## Unlisted

Not a section: the bullets name them.
```

## Package

| | |
| --- | --- |
| Marker | `issues/package` |
| Title | `<repository> <version>` |

```markdown
<!-- style: issues/package -->
## What

The package coordinate-core 0.5.0.
```

## Question

| | |
| --- | --- |
| Marker | `issues/question` |
| Title | the question, ending with a question mark |

- `## Recommendation` (never left out): the first sentence names the option the asker would take.
- `## Other options`: a numbered list.
- `## Context`: citations only.

## Gate

| | |
| --- | --- |
| Marker | `issues/gate` |
| Title | the human's action in the imperative: `Create the six issue types` |

- `## What` (never left out): what the human does, as numbered steps.
- `## Why`: the decision or row that needs it, cited.
- `## Proof`: what the session checks to see it done.

## Note

A note comes from outside. It needs no template.
"""

PULLS = """\
# Pull requests and commits

## PR

| | |
| --- | --- |
| Marker | `pulls/pr` |
| Title | the subject of the behavior commit, without its type |

Sections, in this order:

- `## What` (never left out): one sentence that states the whole change. Then one bullet per
  part of the change.
- `## Why`: the plan step or the row, cited.
- `## Proof`: the test run. Put long output in `<details>`.
- `## Consumers`: who must act or adopt after the merge, one bullet each.
- `## Decisions taken` (never left out): a numbered list of the decisions this PR took, each
  with its reason. The CLI writes it from `--decision`, or `None.`
- `Closes <URL>`: one line per row or step the PR closes. The CLI writes it from `--closes`.

## Run PR

- `## What`: not the PR's.
"""


@pytest.fixture
def style(tmp_path: Path) -> Path:
    path = tmp_path / "style"
    path.mkdir()
    (path / "issues.md").write_text(ISSUES)
    (path / "pulls.md").write_text(PULLS)
    return path


def fields(text: str) -> list[tuple[str, str, bool]]:
    """The (id, label, required) of every field of a generated form, in order."""
    out = []
    for item in text.split("\n  - type: ")[1:]:
        ident = re.search(r"^    id: (.+)$", item, re.M)
        label = re.search(r'^      label: "(.+)"$', item, re.M)
        assert ident, item
        assert label, item
        out.append((ident[1], label[1], "      required: true" in item))
    return out


def test_every_form_and_the_pr_template_are_generated(style: Path) -> None:
    files = forms.generate(style)
    expected = {Path(".github/ISSUE_TEMPLATE") / f"{kind}.yml" for kind in KINDS}
    assert set(files) == expected | {Path(".github/pull_request_template.md")}


def test_a_form_carries_its_type_and_no_title_prefix(style: Path) -> None:
    for kind in KINDS:
        text = forms.generate(style)[Path(".github/ISSUE_TEMPLATE") / f"{kind}.yml"]
        assert f"\ntype: {kind}\n" in text
        assert "\ntitle:" not in text
        assert "kind:" not in text
        assert "id: by\n" not in text


def test_a_row_has_one_field_per_section_in_order(style: Path) -> None:
    files = forms.generate(style)
    for kind in ("change", "gap"):
        text = files[Path(f".github/ISSUE_TEMPLATE/{kind}.yml")]
        assert fields(text) == [
            ("what", "What", True),
            ("why", "Why", False),
            ("proof", "Proof", False),
            ("consumers", "Consumers", False),
        ]
        assert "Add bullets for the parts when there are several." in text
    assert "`Refuse a thing`" in files[Path(".github/ISSUE_TEMPLATE/change.yml")]
    assert "`issue new doubles`" in files[Path(".github/ISSUE_TEMPLATE/gap.yml")]


def test_question_and_gate_follow_their_templates(style: Path) -> None:
    files = forms.generate(style)
    question = files[Path(".github/ISSUE_TEMPLATE/question.yml")]
    assert fields(question) == [
        ("recommendation", "Recommendation", True),
        ("other-options", "Other options", False),
        ("context", "Context", False),
    ]
    assert 'labels: ["gate:G5"]' in question
    gate = files[Path(".github/ISSUE_TEMPLATE/gate.yml")]
    assert fields(gate) == [
        ("what", "What", True),
        ("why", "Why", False),
        ("proof", "Proof", False),
    ]


def test_a_template_without_section_bullets_takes_its_example_headings(style: Path) -> None:
    package = forms.generate(style)[Path(".github/ISSUE_TEMPLATE/package.yml")]
    assert fields(package) == [("what", "What", True)]


def test_a_note_has_one_field(style: Path) -> None:
    note = forms.generate(style)[Path(".github/ISSUE_TEMPLATE/note.yml")]
    assert fields(note) == [("note", "Note", True)]


def test_the_pr_template_follows_the_pr_sections(style: Path) -> None:
    text = forms.generate(style)[Path(".github/pull_request_template.md")]
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings == ["What", "Why", "Proof", "Consumers", "Decisions taken"]
    assert "None." in text.split("## Decisions taken", 1)[1]
    assert text.rstrip().endswith("Closes <URL>")
    comments = re.findall(r"<!--(.*?)-->", text, re.S)
    assert comments
    assert all("--" not in c and "The CLI" not in c for c in comments)


def test_check_finds_a_form_that_drifted(style: Path, tmp_path: Path) -> None:
    out = tmp_path / "repo"
    assert forms.main(["--style", str(style), "--out", str(out)]) == 0
    assert forms.main(["--style", str(style), "--out", str(out), "--check"]) == 0
    gap = out / ".github" / "ISSUE_TEMPLATE" / "gap.yml"
    gap.write_text(gap.read_text() + "# by hand\n")
    assert forms.main(["--style", str(style), "--out", str(out), "--check"]) == 1


def test_a_missing_template_is_named(tmp_path: Path) -> None:
    (tmp_path / "issues.md").write_text("# Issues\n\n## Package\n\n```markdown\n## What\n```\n")
    (tmp_path / "pulls.md").write_text(PULLS)
    with pytest.raises(SystemExit, match="Row: change or gap"):
        forms.generate(tmp_path)


def test_the_committed_forms_carry_their_type_and_no_prefix() -> None:
    for kind in KINDS:
        text = (ROOT / ".github" / "ISSUE_TEMPLATE" / f"{kind}.yml").read_text()
        assert text.startswith("# Generated by scripts/forms.py")
        assert f"\ntype: {kind}\n" in text
        assert "\ntitle:" not in text
        assert "kind:" not in text
        assert "id: by\n" not in text
    template = (ROOT / ".github" / "pull_request_template.md").read_text()
    assert "by: <session or human>" not in template
    assert template.startswith("## What")
