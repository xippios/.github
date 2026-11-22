"""A blocking finding quotes its rule, and a placed finding still blocks (step 6 of .github 0.5.0).

A finding blocks only where it quotes the sentence of the document that the change breaks
(.github#116). It carries that sentence word for word in `quote`, and the script checks that the
document the finding names holds it, as the review read that document, every run of white space
as one space and nothing else altered. A blocking finding whose quote is missing or not found is
answered once as an invalid verdict, naming the finding and why; where the verdict after it still
holds such a finding, the finding stays as one that does not block, with one line under it in the
comment. The comment shows a finding's quote under it, and the hidden last line carries it; a
finding given before this step has no quote and keeps the standing it was given with, and two
findings are one where every field agrees, the quote included.

A finding against a rule that a document states as one blocks wherever a decision on the pull
request placed it (.github#117, decided on .github#118): the judge's instructions say so, and the
script lets a finding of the run before that blocked stop blocking only as fixed or with the
judge's reason, as it did before this step.

The line of a review without a verdict names an API error by its class and the request's id, and
no text of the upstream's message, in the job log and the job summary alike, on a pull request, on
a range and in a dry run (.github#121).

The tests run the script's commands with a fake Messages client; no test needs a key or the
network."""

import json
import os
import subprocess
from pathlib import Path

import anthropic
import conventions as fr
import httpx2
import pytest
from test_conventions import REQUEST, FakeClient, MidStream, call, message, status_error

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
REPO = "xippios/sdk-usda-psd"
BASE = "b" * 40
HEAD = "c" * 40
EARLIER_HEAD = "e" * 40
OWN = "sdk-usda-psd: docs/conventions.md"
CORE = "sdk-core: docs/conventions.md"
CORE_URL = "https://github.com/xippios/sdk-core/blob/main/docs/conventions.md"
# The documents as the review read them: the rule of the repository's own wraps over two lines
# and holds two spaces once, as a document's source may.
OWN_TEXT = (
    "# conventions\n\n## Tests\n\nEvery change of `src/` comes with its test,\n"
    "in the  same commit.\n"
)
CORE_TEXT = "# conventions of sdk-core\n\n## Changelog\n\nA changelog entry never names a commit.\n"
RULE = "Every change of `src/` comes with its test, in the same commit."
CORE_RULE = "A changelog entry never names a commit."
MISSING = "It does not block: it quotes no sentence of the document it names."
NOT_FOUND = "It does not block: its quote was not found in the document it names."
UPSTREAM = "Your credit balance is too low to access the API; go to the billing page."


def finding(
    document: str = f"{OWN}#tests",
    blocking: bool = True,
    quote: str | None = RULE,
    text: str = "The change has no test.",
    file: str = "src/pkg/mod.py",
    line: int | None = 1,
) -> dict:
    """A finding as the judge gives it; ``quote`` None leaves the field out, as a finding given
    before this step has it."""
    item = {"document": document, "file": file, "line": line, "blocking": blocking, "text": text}
    if quote is not None:
        item["quote"] = quote
    return item


def submit(value: str, findings: list[dict], earlier: list[dict] | None = None) -> dict:
    tool_input: dict = {"verdict": value, "findings": findings}
    if earlier is not None:
        tool_input["earlier"] = earlier
    return call("toolu_v", "submit_verdict", tool_input)


def state(number: int, value: str, carried: int | None = None, reason: str = "") -> dict:
    return {"number": number, "state": value, "finding": carried, "reason": reason}


# --- fixtures ----------------------------------------------------------------------------


def write_documents(review: Path) -> None:
    (review / "documents").mkdir(parents=True)
    listed = []
    for number, (label, source, text) in enumerate(
        [(OWN, "main", OWN_TEXT), (CORE, CORE_URL, CORE_TEXT)], 1
    ):
        name = f"{number}-conventions.md"
        (review / "documents" / name).write_text(text)
        listed.append({"label": label, "source": source, "file": f"documents/{name}"})
    (review / "documents.json").write_text(json.dumps(listed))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A prepared pull request: .review with its meta.json and two documents, a source file."""
    ws = tmp_path / "ws"
    review = ws / ".review"
    write_documents(review)
    (review / "diff.patch").write_text("diff --git a/src/pkg/mod.py b/src/pkg/mod.py\n+VALUE = 2\n")
    (review / "log.txt").write_text(f"commit {HEAD}\n")
    meta = {
        "repo": REPO,
        "pr": 11,
        "base": BASE,
        "head": HEAD,
        "main": "origin/main",
        "release": True,
        "since": BASE,
        "tag": "v0.1.0",
    }
    (review / "meta.json").write_text(json.dumps(meta))
    (ws / "src" / "pkg").mkdir(parents=True)
    (ws / "src" / "pkg" / "mod.py").write_text("VALUE = 2\n")
    return ws


@pytest.fixture
def range_workspace(tmp_path: Path) -> Path:
    """A prepared range of a commit with no release tag and no parent: no pull request."""
    ws = tmp_path / "range"
    review = ws / ".review"
    write_documents(review)
    (review / "diff.patch").write_text("diff --git a/src/pkg/mod.py b/src/pkg/mod.py\n+VALUE = 2\n")
    (review / "log.txt").write_text(f"commit {HEAD}\n")
    meta = {"kind": "range", "repo": REPO, "commit": HEAD, "main": "main", "since": None}
    (review / "meta.json").write_text(json.dumps({**meta, "tag": None}))
    (ws / "src" / "pkg").mkdir(parents=True)
    (ws / "src" / "pkg" / "mod.py").write_text("VALUE = 2\n")
    return ws


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """Install a fake client for a script of responses; the secret holds one dummy key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-tests")

    def install(*script):
        client = FakeClient(script)
        monkeypatch.setattr(fr, "make_client", lambda *key: client)
        return client

    return install


@pytest.fixture
def summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "summary.md"
    path.write_text("")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    return path


def review(ws: Path, tmp_path: Path) -> tuple[int, dict]:
    out = tmp_path / "verdict.json"
    code = fr.main(
        ["review", "--workspace", str(ws), "--review", str(ws / ".review"), "--out", str(out)]
    )
    return code, json.loads(out.read_text())


def answer(client: FakeClient, request: int) -> dict:
    """The tool result that the request numbered ``request``, from 0, carried last."""
    return client.messages.requests[request]["messages"][-1]["content"][-1]


def comment_lines(result: dict, head: str = HEAD) -> list[str]:
    body, _ready = fr.verdict_comment(result, REPO, head)
    return body.splitlines()


# --- the quote (.github#116) ---------------------------------------------------------------


def test_a_blocking_finding_with_its_quote_blocks(workspace: Path, tmp_path: Path, api) -> None:
    client = api(message([submit("not ready", [finding()])]))
    code, result = review(workspace, tmp_path)
    assert code == 1
    assert result["verdict"] == "not ready"
    assert result["findings"] == [finding()]
    assert result["summary"].startswith("conventions: verdict=not ready findings=1 blocking=1 ")
    assert result["tool_calls"] == {"submit_verdict": 1}
    assert len(client.messages.requests) == 1


@pytest.mark.parametrize(
    "quote",
    [
        RULE,
        "Every change of `src/` comes with its test,\nin the  same commit.",
        "  Every change of `src/`\tcomes with its test, in the same commit.\n",
    ],
    ids=["one space", "the document's own breaks", "tabs and ends"],
)
def test_a_quote_that_differs_from_its_document_in_white_space_alone_stands(
    workspace: Path, tmp_path: Path, api, quote: str
) -> None:
    """Every run of white space counts as one space, on both sides, and nothing else changes."""
    client = api(message([submit("not ready", [finding(quote=quote)])]))
    code, result = review(workspace, tmp_path)
    assert code == 1
    assert result["findings"][0]["blocking"] is True
    assert result["findings"][0]["quote"] == quote
    assert "unquoted" not in result["findings"][0]
    assert len(client.messages.requests) == 1


@pytest.mark.parametrize(
    "quote",
    [
        "every change of `src/` comes with its test, in the same commit.",
        "Every change of src/ comes with its test, in the same commit.",
        "Every change of `src/` comes with its test in the same commit.",
        "Every change must be reviewed twice.",
    ],
    ids=["case", "markup", "punctuation", "another sentence"],
)
def test_a_quote_altered_otherwise_does_not_stand(
    workspace: Path, tmp_path: Path, api, quote: str
) -> None:
    client = api(
        message([submit("not ready", [finding(quote=quote)])]),
        message([submit("not ready", [finding()])]),
    )
    code, result = review(workspace, tmp_path)
    assert code == 1
    refused = answer(client, 1)
    assert refused["is_error"] is True
    assert f"the quote of finding 1 does not stand in {OWN}" in refused["content"]
    assert result["findings"] == [finding()]


@pytest.mark.parametrize("quote", [None, "", "  \n "], ids=["no field", "empty", "white space"])
def test_a_blocking_finding_without_a_quote_is_asked_once_more(
    workspace: Path, tmp_path: Path, api, quote: str | None
) -> None:
    """The refusal names the finding and why, as an invalid verdict is answered; the judge that
    then quotes the rule gets its blocking finding."""
    client = api(
        message([submit("not ready", [finding(blocking=False, quote=None), finding(quote=quote)])]),
        message([submit("not ready", [finding(blocking=False, quote=None), finding()])]),
    )
    code, result = review(workspace, tmp_path)
    assert code == 1
    refused = answer(client, 1)
    assert refused["is_error"] is True
    assert refused["content"].startswith("invalid verdict: ")
    assert refused["content"].endswith("; call submit_verdict again")
    assert "finding 2 quotes nothing" in refused["content"]
    # The finding that does not block is named nowhere: it needs no quote.
    assert "finding 1" not in refused["content"]
    # The labels the judge may name a document by.
    assert f"({OWN}, {CORE})" in refused["content"]
    assert result["findings"][1] == finding()
    assert result["tool_calls"] == {"submit_verdict": 2}


@pytest.mark.parametrize(
    ("quote", "why", "line"),
    [
        (None, "missing", MISSING),
        ("Every change must be reviewed twice.", "not found", NOT_FOUND),
    ],
    ids=["no quote", "a quote not found"],
)
def test_a_blocking_finding_asked_again_in_vain_stays_as_one_that_does_not_block(
    workspace: Path, tmp_path: Path, api, quote: str | None, why: str, line: str
) -> None:
    """After the second asking the finding stays, does not block, and the comment says why in
    one line under it; with no other finding that blocks the verdict is ready. The comment
    shows no text that the document does not hold as a quote (fix round 1 of #148)."""
    bad = finding(quote=quote)
    note = finding(blocking=False, quote="", text="A note.")
    client = api(
        message([submit("not ready", [bad, note])]),
        message([submit("not ready", [bad, note])]),
    )
    code, result = review(workspace, tmp_path)
    assert code == 0
    assert len(client.messages.requests) == 2
    assert result["verdict"] == "ready"
    assert result["findings"][0] == {**bad, "blocking": False, "unquoted": why}
    assert result["findings"][1] == note
    assert result["summary"].startswith("conventions: verdict=ready findings=2 blocking=0 ")
    lines = comment_lines(result)
    item = lines.index(
        "1. **sdk-usda-psd: docs/conventions.md#tests** The change has no test. "
        "`src/pkg/mod.py:1`. Blocks: no."
    )
    assert lines[item + 1] == f"   {line}"
    assert lines[item + 2].startswith("2. ")
    assert not any(entry.lstrip().startswith(">") for entry in lines)
    assert lines[0] == "<!-- style: reviews/conventions -->"
    assert lines[1].startswith("**Findings.** 2 findings, none blocking, at ")


def test_a_finding_that_still_quotes_its_rule_keeps_blocking_beside_one_that_does_not(
    workspace: Path, tmp_path: Path, api
) -> None:
    bad = finding(quote="Every change must be reviewed twice.", text="Not reviewed twice.")
    client = api(
        message([submit("not ready", [finding(), bad])]),
        message([submit("not ready", [finding(), bad])]),
    )
    code, result = review(workspace, tmp_path)
    assert code == 1
    assert "the quote of finding 2 does not stand in" in answer(client, 1)["content"]
    assert "finding 1" not in answer(client, 1)["content"]
    assert result["verdict"] == "not ready"
    assert [f["blocking"] for f in result["findings"]] == [True, False]
    assert result["findings"][1]["unquoted"] == "not found"


def test_a_quote_of_another_document_than_the_one_named_does_not_stand(
    workspace: Path, tmp_path: Path, api
) -> None:
    """The quote must stand in the document that the finding names, by its label: the rule of
    the repository's own conventions does not stand in sdk-core's, and a document named by no
    label of the review holds no quote."""
    client = api(
        message(
            [
                submit(
                    "not ready",
                    [
                        finding(document=f"{CORE}#changelog"),
                        finding(document="docs/conventions.md#tests"),
                        finding(document=f"{OWN}x#tests"),
                    ],
                )
            ]
        ),
        message(
            [
                submit(
                    "not ready",
                    [
                        finding(document=f"{CORE}#changelog", quote=CORE_RULE),
                        finding(),
                        finding(document=OWN),
                    ],
                )
            ]
        ),
    )
    code, result = review(workspace, tmp_path)
    assert code == 1
    refused = answer(client, 1)["content"]
    assert f"the quote of finding 1 does not stand in {CORE}" in refused
    assert "finding 2 names no document of this review" in refused
    assert "finding 3 names no document of this review" in refused
    assert [f["blocking"] for f in result["findings"]] == [True, True, True]


@pytest.mark.parametrize(
    "quote", [None, "", RULE, "A sentence of no document."], ids=["none", "empty", "found", "other"]
)
def test_a_finding_that_does_not_block_needs_no_quote(
    workspace: Path, tmp_path: Path, api, quote: str | None
) -> None:
    client = api(message([submit("ready", [finding(blocking=False, quote=quote)])]))
    code, result = review(workspace, tmp_path)
    assert code == 0
    assert len(client.messages.requests) == 1
    # A quote that its document does not hold is marked, so the comment shows it as none (fix
    # round 2 of #148); the finding's standing does not change.
    mark = {"quote_stands": False} if quote == "A sentence of no document." else {}
    assert result["findings"] == [{**finding(blocking=False, quote=quote), **mark}]


def test_a_quote_of_a_range_is_checked_as_a_pull_requests(
    range_workspace: Path, tmp_path: Path, api
) -> None:
    """The run on a range judges by the same rule and the same code."""
    client = api(
        message([submit("not ready", [finding(quote=None, file="", line=None)])]),
        message([submit("not ready", [finding(quote=None, file="", line=None)])]),
    )
    code, result = review(range_workspace, tmp_path)
    assert code == 0
    assert "finding 1 quotes nothing" in answer(client, 1)["content"]
    assert result["findings"] == [
        {**finding(quote=None, file="", line=None), "blocking": False, "unquoted": "missing"}
    ]
    assert result["range"]["kind"] == "range"
    lines = comment_lines(result)
    item = lines.index(
        "1. **sdk-usda-psd: docs/conventions.md#tests** The change has no test. Blocks: no."
    )
    assert lines[item + 1] == f"   {MISSING}"


def test_a_key_in_a_quote_is_redacted(workspace: Path, tmp_path: Path, api) -> None:
    key = "sk-ant-" + "api03-" + "Qz7" * 8
    api(message([submit("ready", [finding(blocking=False, quote=f"Never commit {key}.")])]))
    code, result = review(workspace, tmp_path)
    assert code == 0
    assert result["findings"][0]["quote"] == "Never commit [redacted]."
    assert key not in (tmp_path / "verdict.json").read_text()


# --- the comment and the hidden line -----------------------------------------------------


def verdict_file(verdict: str, findings: list[dict], earlier: dict | None = None) -> dict:
    return {
        "verdict": verdict,
        "findings": findings,
        "range": {"release": True, "since": BASE, "tag": "v0.1.0"},
        "documents": [OWN, CORE],
        "summary": "conventions: verdict=…",
        **({"earlier": earlier} if earlier else {}),
    }


def test_the_comment_shows_the_quote_under_its_finding_and_the_hidden_line_carries_it() -> None:
    """A reader sees the rule that blocks; a finding without a quote is written to the hidden
    line as before this step, with the five fields alone."""
    quoted = finding(quote="Every change of `src/`\ncomes with its test --> <b>now</b>.")
    plain = finding(blocking=False, quote=None, text="A note.", file="", line=None)
    empty = finding(blocking=False, quote="", text="Another note.", file="", line=None)
    lines = comment_lines(verdict_file("not ready", [quoted, plain, empty]))
    item = lines.index(
        "1. **sdk-usda-psd: docs/conventions.md#tests** The change has no test. "
        "`src/pkg/mod.py:1`. Blocks: yes."
    )
    assert lines[item + 1] == "   > Every change of `src/` comes with its test --> <b>now</b>."
    assert lines[item + 2] == "2. **sdk-usda-psd: docs/conventions.md#tests** A note. Blocks: no."
    assert lines[item + 3] == (
        "3. **sdk-usda-psd: docs/conventions.md#tests** Another note. Blocks: no."
    )
    last = lines[-1]
    assert "<" not in last.removeprefix("<!--")
    run = json.loads(last.removeprefix("<!-- conventions-run: ").removesuffix(" -->"))
    assert run["findings"] == [quoted, plain, {key: empty[key] for key in fr.FINDING_KEYS}]
    assert "quote" not in run["findings"][1]
    read = fr.run_state("\n".join(lines))
    assert read is not None
    assert read.findings == [quoted, plain, {key: empty[key] for key in fr.FINDING_KEYS}]


def test_a_finding_number_ten_keeps_its_quote_inside_its_item() -> None:
    findings = [finding(blocking=False, quote=None, text=f"Note {n}.") for n in range(1, 10)]
    lines = comment_lines(verdict_file("not ready", [*findings, finding()]))
    item = next(n for n, line in enumerate(lines) if line.startswith("10. "))
    assert lines[item + 1] == f"    > {RULE}"


def old_comment(findings: list[dict], head: str = EARLIER_HEAD) -> str:
    """The check's comment as a run before this step wrote it: five fields to a finding."""
    run = {"head": head, "findings": findings}
    blob = json.dumps(run, ensure_ascii=True, separators=(",", ":"))
    hidden = (
        "<!-- conventions-run: " + blob.replace("<", "\\u003c").replace(">", "\\u003e") + " -->"
    )
    return (
        "<!-- style: reviews/conventions -->\n"
        f"**Blocked.** 1 finding, 1 blocking, at https://github.com/{REPO}/commit/{head}.\n\n"
        f"Judged: the pull request's own diff.\n\n{hidden}\n"
    )


def with_earlier(workspace: Path, findings: list[dict], decisions: list[str] = ()) -> None:
    """The run before as prepare writes it, with the opener's decisions on the pull request."""
    review_dir = workspace / ".review"
    numbered = [{"number": n, **f, "file_changed": False} for n, f in enumerate(findings, 1)]
    decided = [{"created_at": "2026-11-22T10:00:00Z", "body": body} for body in decisions]
    earlier = {"head": EARLIER_HEAD, "findings": numbered, "decisions": decided}
    (review_dir / "earlier.json").write_text(json.dumps(earlier))
    compared = {
        "head": EARLIER_HEAD,
        "compared": True,
        "files": [],
        "head_files": ["src/pkg/mod.py"],
    }
    (review_dir / "changed.json").write_text(json.dumps(compared))


UNBLOCKED = (
    "an open one that blocked, carried by a finding that does not block, gives in reason why "
    "it no longer blocks"
)


def test_an_earlier_finding_without_a_quote_keeps_the_standing_it_was_given_with(
    workspace: Path, tmp_path: Path, api
) -> None:
    """A finding that blocked before this step has no quote: it reads as a finding that blocked,
    and it stops blocking only as it did before, fixed or with the judge's reason."""
    old = finding(quote=None)
    run = fr.run_state(old_comment([old]))
    assert run is not None
    assert run.findings == [old]
    assert run.ready is False
    with_earlier(workspace, run.findings)
    material = fr.load_material(workspace, workspace / ".review")
    assert material.earlier is not None
    assert material.earlier.findings == [old]
    carrier = finding(blocking=False, quote=None)
    client = api(
        message([submit("ready", [carrier], [state(1, "open", 1)])]),
        message([submit("ready", [], [state(1, "fixed")])]),
    )
    code, result = review(workspace, tmp_path)
    assert code == 0
    assert (
        answer(client, 1)["content"] == f"invalid verdict: {UNBLOCKED}; call submit_verdict again"
    )
    assert result["earlier"]["findings"] == [
        {**old, "state": "fixed", "finding": None, "reason": ""}
    ]


def test_an_earlier_verdict_file_without_quotes_reads_as_before(tmp_path: Path) -> None:
    """A dry run's `--earlier` takes a verdict file written before this step, and one after."""
    old = finding(quote=None)
    data = {"verdict": "not ready", "repo": REPO, "pr": 7, "head": EARLIER_HEAD}
    path = tmp_path / "earlier.json"
    path.write_text(json.dumps({**data, "findings": [{**old, "since": "changed"}]}))
    assert fr.run_from_verdict(path, REPO, 7).findings == [old]
    path.write_text(json.dumps({**data, "findings": [{**finding(), "unquoted": "missing"}]}))
    assert fr.run_from_verdict(path, REPO, 7).findings == [finding()]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def scrubbed_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """git exports GIT_DIR, GIT_INDEX_FILE and more to hooks: none may reach a test's git."""
    keep = {
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    }
    for name in list(os.environ):
        if name.startswith("GIT_") and name not in keep:
            monkeypatch.delenv(name)


def test_two_findings_are_one_where_every_field_agrees_the_quote_included(
    tmp_path: Path, scrubbed_git: None
) -> None:
    """Two runs before give their findings their states once each: a finding is the other's
    where the five fields and the quote agree, and a finding with no quote is one with an empty
    quote (step 4's rule, kept in step with the quote)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    (ws / "src").mkdir()
    (ws / "src" / "mod.py").write_text("VALUE = 1\n")
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", "first")
    first = git(ws, "rev-parse", "HEAD")
    (ws / "src" / "mod.py").write_text("VALUE = 2\n")
    git(ws, "commit", "-q", "-am", "second")
    second = git(ws, "rev-parse", "HEAD")
    review_dir = ws / ".review"
    review_dir.mkdir()
    one = finding(file="src/mod.py")
    other = finding(file="src/mod.py", quote="Every change of `src/` comes with its test,")
    note = finding(blocking=False, quote=None, file="", line=None, text="A note.")
    runs = [
        fr.EarlierRun(first, [one, note]),
        fr.EarlierRun(second, [one, other, {**note, "quote": ""}]),
    ]
    fr.write_earlier(ws, REPO, review_dir, b"{}", second, None, runs=runs)
    earlier = json.loads((review_dir / "earlier.json").read_text())
    kept = [
        {key: value for key, value in f.items() if key not in ("number", "file_changed", "judged")}
        for f in earlier["findings"]
    ]
    assert kept == [one, note, other]
    assert earlier["findings"][2]["judged"] == second


# --- the placed finding (.github#117, decided on .github#118) ----------------------------

PLACED = (
    "<!-- style: comments/decisions -->\n"
    "**Decided.** Finding 1: **Carried** into the next patch, 0.5.1, with its row.\n"
)
STANDS = "Placing it in the next patch shows no written rule kept: the rule still binds."


def test_a_placed_finding_still_blocks_on_a_pull_request_whose_decision_places_it(
    workspace: Path, tmp_path: Path, api
) -> None:
    """The opener's decision places a finding against a written rule in the next patch: the
    script refuses `decided` without the judge's reason, as before this step, and the judge that
    keeps it open carries it by a finding that blocks; the release stays not ready."""
    with_earlier(workspace, [finding()], [PLACED])
    material = fr.load_material(workspace, workspace / ".review")
    assert material.earlier is not None
    assert material.earlier.decisions == 1
    client = api(
        message([submit("ready", [], [state(1, "decided")])]),
        message([submit("not ready", [finding()], [state(1, "open", 1, STANDS)])]),
    )
    code, result = review(workspace, tmp_path)
    assert code == 1
    assert answer(client, 1)["content"] == (
        "invalid verdict: a decided one that blocked gives in reason why the opener's decision "
        "shows that no written rule is broken; call submit_verdict again"
    )
    assert result["verdict"] == "not ready"
    assert result["findings"] == [{**finding(), "since": "unchanged"}]
    before = result["earlier"]["findings"][0]
    assert (before["state"], before["finding"], before["reason"]) == ("open", 1, STANDS)
    assert fr.became(before) == (
        f"Open: finding 1 above. The opener decided otherwise, and the rule stands: {STANDS}"
    )
    lines = comment_lines(result)
    assert lines[1].startswith("**Blocked.** 1 finding, 1 blocking, at ")


def flat(text: str) -> str:
    return " ".join(text.split())


QUOTE_RULE = (
    "It blocks when the change breaks a rule the document states as one: a must, a never, a "
    "refusal, a form the record is held to, and only where `quote` holds the sentence that states "
    "the rule, word for word as the document that `document` names holds it."
)
PLACED_RULE = (
    "A finding against a rule that a document states as one blocks wherever a decision on the "
    "pull request placed it: a decision of the opener that places it in a later package or patch "
    "does not stop it from blocking."
)


def test_the_judges_instructions_state_both_rules() -> None:
    pull_request, ranged = flat(fr.INSTRUCTIONS), flat(fr.RANGE_INSTRUCTIONS)
    assert QUOTE_RULE in pull_request
    assert QUOTE_RULE in ranged
    assert (
        "So a case that the wording of the documents leaves open is a finding that does not "
        "block, on every pull request alike." in pull_request
    )
    assert (
        "So a case that the wording of the documents leaves open is a finding that does not "
        "block, on every range alike." in ranged
    )
    assert PLACED_RULE in pull_request
    # A range has no pull request and no decision that places a finding.
    assert "decision" not in ranged
    for text in (pull_request, ranged):
        assert (
            "and in `quote` the sentence of that document it breaks, empty where it quotes none"
            in text
        )


@pytest.mark.parametrize("tools", [fr.TOOLS, fr.RANGE_TOOLS], ids=["pull request", "range"])
def test_the_tool_asks_each_finding_for_its_quote(tools: list) -> None:
    schema = next(tool for tool in tools if tool["name"] == "submit_verdict")["input_schema"]
    item = schema["properties"]["findings"]["items"]
    assert list(item["properties"]) == ["document", "file", "line", "blocking", "text", "quote"]
    assert item["required"] == ["document", "file", "line", "blocking", "text", "quote"]
    assert item["properties"]["quote"]["type"] == "string"
    assert "word for word" in item["properties"]["quote"]["description"]


# --- the line of an API error (.github#121) ----------------------------------------------


def response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=REQUEST, headers={"request-id": "req_test1"})


ERRORS = [
    (status_error(anthropic.BadRequestError, 400, UPSTREAM), "BadRequestError (request req_test1)"),
    (
        anthropic.InternalServerError(UPSTREAM, response=response(503), body=UPSTREAM),
        "InternalServerError (request req_test1)",
    ),
    (
        MidStream(status_error(anthropic.APIStatusError, 200, UPSTREAM, "overloaded_error")),
        "APIStatusError (request req_test1)",
    ),
    (anthropic.APIConnectionError(message=UPSTREAM, request=REQUEST), "APIConnectionError"),
    (MidStream(httpx2.RemoteProtocolError(UPSTREAM, request=REQUEST)), "RemoteProtocolError"),
]
IDS = ["status", "body without an error", "error event", "connection", "lost stream"]


def no_upstream(text: str) -> None:
    assert "credit balance" not in text
    assert "billing" not in text


@pytest.mark.parametrize(("error", "named"), ERRORS, ids=IDS)
def test_the_line_of_an_api_error_names_its_class_and_request_on_a_pull_request(
    workspace: Path, tmp_path: Path, api, summary: Path, capsys, error, named: str
) -> None:
    api(error)
    code, result = review(workspace, tmp_path)
    captured = capsys.readouterr()
    assert code == 2
    assert result["reason"] == f"API error: {named}"
    line = f"conventions: no verdict (API error: {named}) turns=0 "
    assert captured.out.startswith(line)
    assert summary.read_text().startswith(line)
    for text in (captured.out, captured.err, summary.read_text(), json.dumps(result)):
        no_upstream(text)
    # The Verdict step's job summary of a run without a verdict carries that line alone.
    no_upstream(fr.no_verdict(result))
    assert f"(API error: {named})" in fr.no_verdict(result)


@pytest.mark.parametrize(("error", "named"), ERRORS, ids=IDS)
def test_the_line_of_an_api_error_names_its_class_and_request_on_a_range(
    range_workspace: Path, tmp_path: Path, api, summary: Path, capsys, error, named: str
) -> None:
    api(error)
    code, result = review(range_workspace, tmp_path)
    captured = capsys.readouterr()
    assert code == 2
    assert result["range"]["kind"] == "range"
    line = f"conventions: no verdict (API error: {named}) turns=0 "
    assert captured.out.startswith(line)
    assert summary.read_text().startswith(line)
    for text in (captured.out, captured.err, summary.read_text(), json.dumps(result)):
        no_upstream(text)


@pytest.mark.parametrize("target", ["--pr", "--commit"])
def test_the_line_of_an_api_error_names_its_class_and_request_in_a_dry_run(
    workspace: Path,
    range_workspace: Path,
    tmp_path: Path,
    api,
    summary: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    target: str,
) -> None:
    """A dry run of a pull request and of a commit's range print the same line."""
    ws = workspace if target == "--pr" else range_workspace
    monkeypatch.setattr(fr, "_prepare", lambda args, summary: (ws, 2))
    monkeypatch.setattr(fr, "_prepare_range", lambda args, summary: (ws, 2))
    api(status_error(anthropic.BadRequestError, 400, UPSTREAM))
    out = tmp_path / "dry.json"
    value = "7" if target == "--pr" else HEAD
    code = fr.main(["dry-run", "--repo", REPO, target, value, "--out", str(out)])
    captured = capsys.readouterr()
    assert code == 2
    line = "conventions: no verdict (API error: BadRequestError (request req_test1)) turns=0 "
    assert captured.out.startswith(line)
    assert summary.read_text().startswith(line)
    for text in (captured.out, captured.err, summary.read_text(), out.read_text()):
        no_upstream(text)


def test_a_dry_run_prints_the_quote_and_the_line_of_a_finding_that_no_longer_blocks(
    workspace: Path, tmp_path: Path, api, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(fr, "_prepare", lambda args, summary: (workspace, 2))
    bad = finding(quote="Every change must be reviewed twice.")
    api(
        message([submit("not ready", [finding(), bad])]),
        message([submit("not ready", [finding(), bad])]),
    )
    assert fr.main(["dry-run", "--repo", REPO, "--pr", "7"]) == 1
    out = capsys.readouterr().out.splitlines()
    said = f"{OWN}#tests: The change has no test."
    assert out[-4:] == [
        f"src/pkg/mod.py:1 [blocking] {said}",
        # As the dry run prints every text: a backtick as its escape.
        f"   > {fr.printable(RULE)}",
        f"src/pkg/mod.py:1 [non-blocking] {said}",
        # A quote that does not stand is printed as no quote (fix round 1 of #148).
        f"   {NOT_FOUND}",
    ]
    assert out[-5].startswith("conventions: verdict=not ready findings=2 blocking=1 ")


# --- the README --------------------------------------------------------------------------


def entry(name: str) -> str:
    text = README.split(f"\n- **`.github/workflows/{name}`**", 1)[1]
    return flat(text.split("\n- **`.github/workflows/", 1)[0])


def test_the_readme_says_the_three_rules() -> None:
    pull_request, ranged = entry("conventions.yml"), entry("conventions-range.yml")
    assert (
        "a finding blocks only where it quotes the sentence of the document that the change "
        "breaks" in pull_request
    )
    assert "every run of white space as one space and nothing else altered" in pull_request
    assert "with one line under it that says its quote was not found" in pull_request
    assert "So a case that the wording of the documents leaves open does not block" in pull_request
    assert "The comment shows the quote under its finding" in pull_request
    assert (
        "a finding against a rule that a document states as one blocks wherever a decision on "
        "the pull request placed it" in pull_request
    )
    assert (
        "An API error is named by the SDK's error class and the request's id where the error "
        "carries one, never by the upstream's message, in the job log and the job summary alike"
        in pull_request
    )
    assert "its redacted message" not in pull_request
    assert "a finding of a range blocks only where it quotes the sentence" in ranged
    assert "the line of an API error" in ranged
    # The two rules of fix round 1 of #148, where the README says the quote rule.
    carried = (
        "a finding that carries, as open, a finding of the run before that blocked keeps blocking"
    )
    one_rule = (
        "The verdict is `ready` exactly where no finding blocks once these rules are applied, "
        "and `not ready` exactly where one blocks, whatever verdict the judge gave"
    )
    for text in (carried, one_rule):
        assert text in pull_request, text
        assert text in ranged, text
    assert "The comment shows no text as a quote that the document does not hold" in pull_request
    assert "and where no finding blocks then, the verdict is `ready`" not in pull_request


# --- fix round 1 of #148: a carrier keeps blocking, and one rule for the verdict ----------

CARRIES = (
    "It blocks as the finding of the run before that it carries did, though its quote was not "
    "found in the document it names."
)
CARRIES_MISSING = (
    "It blocks as the finding of the run before that it carries did, though it quotes no "
    "sentence of the document it names."
)


@pytest.mark.parametrize("decided", [True, False], ids=["a decision places it", "no decision"])
@pytest.mark.parametrize(
    ("quote", "line"),
    [("Every change must be reviewed twice.", CARRIES), (None, CARRIES_MISSING)],
    ids=["a quote not found", "no quote"],
)
def test_a_carrier_of_a_finding_that_blocked_keeps_blocking_without_its_quote(
    workspace: Path, tmp_path: Path, api, decided: bool, quote: str | None, line: str
) -> None:
    """A finding that blocked a release is not released by a misquote: its carrier is asked once
    for the sentence as any blocking finding is, and where the verdict after it still holds the
    carrier without a quote that stands, the carrier keeps blocking and the run ends not ready.
    The entry of the run before reads as carried by a finding that blocks, never as one that no
    longer blocks (finding 1 of the review of #148)."""
    with_earlier(workspace, [finding()], [PLACED] if decided else [])
    carrier = finding(quote=quote, text="The change has no test, still.")
    states = [state(1, "open", 1, STANDS if decided else "")]
    client = api(
        message([submit("not ready", [carrier], states)]),
        message([submit("not ready", [carrier], states)]),
    )
    code, result = review(workspace, tmp_path)
    assert code == 1
    refused = answer(client, 1)["content"]
    assert refused.startswith("invalid verdict: ")
    assert "finding 1 carries a finding of the run before that blocked and keeps blocking" in (
        refused
    )
    assert result["verdict"] == "not ready"
    why = "not found" if quote else "missing"
    assert result["findings"] == [{**carrier, "unquoted": why, "since": "unchanged"}]
    assert result["summary"].startswith("conventions: verdict=not ready findings=1 blocking=1 ")
    before = result["earlier"]["findings"][0]
    assert "unblocked" not in before
    words = fr.became(before)
    assert "no longer blocks" not in words
    if decided:
        assert words == (
            f"Open: finding 1 above. The opener decided otherwise, and the rule stands: {STANDS}"
        )
    else:
        assert words == "Open: finding 1 above."
    lines = comment_lines(result)
    assert lines[1].startswith("**Blocked.** 1 finding, 1 blocking, at ")
    item = lines.index(
        "1. **sdk-usda-psd: docs/conventions.md#tests** The change has no test, still. "
        "`src/pkg/mod.py:1`. Blocks: yes. Its file is unchanged since the head judged before."
    )
    assert lines[item + 1] == f"   {line}"
    # No text the document does not hold shows as a quote.
    assert not any(entry.lstrip().startswith(">") for entry in lines)


def test_a_carrier_that_the_judge_takes_from_blocking_with_its_reason_needs_no_quote(
    workspace: Path, tmp_path: Path, api
) -> None:
    """The judge's reason still lets a finding that blocked stop blocking, as before this step:
    a carrier that does not block needs no quote."""
    with_earlier(workspace, [finding()])
    carrier = finding(blocking=False, quote=None)
    reason = "The rule binds release pull requests alone."
    client = api(message([submit("ready", [carrier], [state(1, "open", 1, reason)])]))
    code, result = review(workspace, tmp_path)
    assert code == 0
    assert len(client.messages.requests) == 1
    assert result["earlier"]["findings"][0]["unblocked"] is True


BAD = finding(quote="Every change must be reviewed twice.")
NOTE = finding(blocking=False, quote=None, text="A note.")


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ([("not ready", [NOTE])], "ready"),
        ([("not ready", [])], "ready"),
        ([("ready", [finding()])], "not ready"),
        ([("not ready", [BAD]), ("not ready", [{**BAD, "blocking": False}])], "ready"),
        ([("not ready", [BAD]), ("not ready", [BAD])], "ready"),
        ([("ready", [BAD]), ("ready", [finding()])], "not ready"),
    ],
    ids=[
        "no asking, not ready with no finding that blocks",
        "no asking, not ready with no finding",
        "no asking, ready with a finding that blocks",
        "asked, the judge takes the blocking back and keeps not ready",
        "asked, the script takes the blocking",
        "asked, the judge quotes the rule and says ready",
    ],
)
def test_the_verdict_is_ready_exactly_where_no_finding_blocks(
    workspace: Path, tmp_path: Path, api, verdicts: list, expected: str
) -> None:
    """One rule on every path, whether the script asked or not: the judge's word on the verdict
    yields to its findings once the script's rules are applied (finding 2 of the review of
    #148)."""
    api(*(message([submit(value, findings)]) for value, findings in verdicts))
    code, result = review(workspace, tmp_path)
    blocking = sum(1 for f in result["findings"] if f["blocking"])
    assert result["verdict"] == expected
    assert (expected == "not ready") is (blocking > 0)
    assert code == (1 if blocking else 0)
    lines = comment_lines(result)
    assert lines[1].startswith("**Blocked.**" if blocking else ("**Findings.**", "**Approved.**"))


@pytest.mark.parametrize("case", ["a carrier", "not ready with no finding that blocks"])
def test_a_range_keeps_both_rules(range_workspace: Path, tmp_path: Path, api, case: str) -> None:
    """A range is served by the same code: its carrier of a finding that blocked keeps blocking
    without a quote that stands, and its verdict is ready exactly where no finding blocks."""
    if case == "a carrier":
        with_earlier(range_workspace, [finding(file="", line=None)])
        carrier = finding(quote=None, file="", line=None)
        states = [state(1, "open", 1)]
        api(
            message([submit("not ready", [carrier], states)]),
            message([submit("not ready", [carrier], states)]),
        )
        code, result = review(range_workspace, tmp_path)
        assert code == 1
        assert result["verdict"] == "not ready"
        assert result["findings"] == [{**carrier, "unquoted": "missing"}]
        assert "unblocked" not in result["earlier"]["findings"][0]
    else:
        api(message([submit("not ready", [NOTE])]))
        code, result = review(range_workspace, tmp_path)
        assert code == 0
        assert result["verdict"] == "ready"
    assert result["range"]["kind"] == "range"


# --- fix round 2 of #148: a quote shows only where its document holds it -----------------

HELD_NOT = "Every change must be reviewed twice."


def no_blocking(quote: str, document: str = f"{OWN}#tests", where: str = "pull request") -> dict:
    """A finding that does not block, with its file as each kind of review names one."""
    if where == "range":
        return finding(blocking=False, quote=quote, document=document, file="", line=None)
    return finding(blocking=False, quote=quote, document=document)


@pytest.mark.parametrize("where", ["pull request", "range"])
@pytest.mark.parametrize(
    "case",
    [
        "a quote that stands",
        "a quote its document does not hold",
        "no document of the review",
        "taken back after the asking",
    ],
)
def test_a_quote_shows_only_where_its_document_holds_it(
    workspace: Path,
    range_workspace: Path,
    tmp_path: Path,
    api,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    where: str,
    case: str,
) -> None:
    """The quote of every finding is checked by the rule of a blocking one, and the comment and
    the dry run show it only where its document holds it, under a finding that does not block
    too. Where it does not stand under such a finding, no quote shows and no line is added, since
    its standing does not change; the hidden last line carries the quote as before (finding 1 of
    the re-review of #148)."""
    ws = workspace if where == "pull request" else range_workspace
    if case == "a quote that stands":
        script = [[no_blocking(RULE, where=where)]]
    elif case == "a quote its document does not hold":
        script = [[no_blocking(HELD_NOT, where=where)]]
    elif case == "no document of the review":
        script = [[no_blocking(RULE, document="docs/conventions.md#tests", where=where)]]
    else:
        refused = {**no_blocking(HELD_NOT, where=where), "blocking": True}
        script = [[refused], [no_blocking(HELD_NOT, where=where)]]
    api(*(message([submit("not ready", findings)]) for findings in script))
    monkeypatch.setattr(fr, "_prepare", lambda args, summary: (ws, 2))
    monkeypatch.setattr(fr, "_prepare_range", lambda args, summary: (ws, 2))
    out = tmp_path / "dry.json"
    target = ["--pr", "7"] if where == "pull request" else ["--commit", HEAD]
    assert fr.main(["dry-run", "--repo", REPO, *target, "--out", str(out)]) == 0
    printed = capsys.readouterr().out.splitlines()
    result = json.loads(out.read_text())
    given = script[-1][0]
    stands = case == "a quote that stands"
    assert result["verdict"] == "ready"
    assert result["findings"][0]["blocking"] is False
    assert result["findings"][0]["quote"] == given["quote"]
    assert "unquoted" not in result["findings"][0]
    assert ("quote_stands" not in result["findings"][0]) is stands
    lines = comment_lines(result)
    item = next(n for n, line in enumerate(lines) if line.startswith("1. "))
    if stands:
        assert lines[item + 1] == f"   > {RULE}"
        assert printed[-1] == f"   > {fr.printable(RULE)}"
    else:
        assert lines[item + 1] == ""
        assert not any(line.lstrip().startswith(">") for line in lines)
        assert "[non-blocking]" in printed[-1]
        assert not any(line.lstrip().startswith(">") for line in printed)
    # The hidden last line carries the quote as it is written today.
    run = json.loads(lines[-1].removeprefix("<!-- conventions-run: ").removesuffix(" -->"))
    assert run["findings"][0]["quote"] == given["quote"]
