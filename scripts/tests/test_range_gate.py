"""The job `gate` of `conventions-range.yml` knows the merge that completes a package (step 3 of
.github 0.5.0, .github#99). On a push to the default branch it finds the pull request whose merge
made the pushed commit and lets the range be judged where that pull request is no release PR,
carries a milestone, and closes every open step of that milestone; on a dispatch it always lets it.
GitHub closes the issues that a merged pull request closes seconds after the merge, so a step that
the pull request closes counts as closed though the answer still shows it open. The milestone's
open issues are read from the milestone page by page, never by a search, whose index can lag just
after a merge; an issue without a type is a step by the step form of its title, so a package never
looks complete because the types could not be read; and an error of a call fails closed.

The tests run the step's own `run:` text, as the workflow holds it, in the environment the runner
gives a step, with a stub `gh` first on the path that answers from pages the test gives and logs
its calls."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import conventions as fr
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "conventions.py"
WORKFLOW = (ROOT / ".github" / "workflows" / "conventions-range.yml").read_text()
REPO = "xippios/sdk-usda-psd"
SHA = "c" * 40
OTHER_SHA = "d" * 40
MILESTONE = {"number": 5, "title": "sdk-usda-psd 0.5.0"}
TITLE = "0.5.0 Step 3: The gate knows the merge that completes a package"
CALL = 'python3 -I "$GITHUB_WORKSPACE/.sdk-gates/scripts/conventions.py" range-gate\n'
BASH = shutil.which("bash") or "bash"
# A stub `gh`: it logs each call and answers it with the page of its kind that the call asks for,
# from `answers.json` beside it. A GraphQL query is the milestone's issues or the pull request's
# closing issues, its page the number of its cursor `c<n>`; a REST call is the pull requests of a
# commit, its page the number after `page=`. A page the test gave none of fails the call, and a
# page with `sleep` answers after that many seconds.
STUB = """\
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
args = sys.argv[1:]
with (HERE / "calls").open("a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
fields = {}
for flag, value in zip(args, args[1:]):
    if flag in ("-f", "-F"):
        key, _, text = value.partition("=")
        fields[key] = text
if args[:1] != ["api"] or len(args) < 2:
    sys.exit("stub: no api call")
if args[1] == "graphql":
    kind = "closing" if "closingIssuesReferences" in fields.get("query", "") else "issues"
    cursor = fields.get("cursor", "")
    index = int(cursor[1:]) if cursor else 0
else:
    kind = "pulls"
    index = int(args[1].rsplit("&page=", 1)[1]) - 1 if "&page=" in args[1] else 0
pages = json.loads((HERE / "answers.json").read_text()).get(kind, [])
if index >= len(pages):
    sys.exit(f"stub: no page {index} of {kind}")
page = pages[index]
time.sleep(page.get("sleep", 0))
sys.stdout.write(page.get("stdout", ""))
sys.stderr.write(page.get("stderr", ""))
sys.exit(page.get("exit", 0))
"""
# The Python of the job's step where neither the SDK nor its HTTP client can be imported: the
# program runs the script as `python3 -I <script> <command>` does.
WITHOUT_SDK = (
    "import runpy, sys\n"
    "sys.modules['anthropic'] = None\n"
    "sys.modules['httpx2'] = None\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def step(name: str) -> str:
    """The one-line `run:` of the step `name` of conventions-range.yml."""
    block = WORKFLOW.split(f"      - name: {name}\n", 1)[1].split("\n      - name: ", 1)[0]
    return block.split("\n        run: ", 1)[1].split("\n", 1)[0] + "\n"


def ok(data: object) -> dict:
    """A page that a call answers with, `gh` ending without an error."""
    return {"stdout": json.dumps(data)}


def pull(
    number: int = 7,
    *,
    title: str = TITLE,
    labels: tuple[str, ...] = (),
    milestone: dict | None = MILESTONE,
    merged: bool = True,
    merge_sha: str = SHA,
) -> dict:
    """A pull request of a commit as GitHub's REST answer gives it."""
    return {
        "number": number,
        "state": "closed" if merged else "open",
        "title": title,
        "labels": [{"name": label} for label in labels],
        "milestone": milestone,
        "merged_at": "2026-11-21T21:00:38Z" if merged else None,
        "merge_commit_sha": merge_sha,
    }


def issue(number: int, kind: str | None = "step", title: str | None = None) -> dict:
    """An open issue of the milestone as the GraphQL answer gives it; `kind` None for no type."""
    return {
        "number": number,
        "title": title if title is not None else f"0.5.0 Step {number}: A step",
        "issueType": None if kind is None else {"name": kind},
    }


def closing(number: int, repo: str = REPO) -> dict:
    """A closing issue of the pull request as the GraphQL answer gives it."""
    return {"number": number, "repository": {"nameWithOwner": repo}}


def pages(path: tuple[str, ...], connection: str, *nodes: list[dict]) -> list[dict]:
    """The pages of a GraphQL connection under `data.repository` and `path`, each with its
    `pageInfo`: a page before the last says that one follows, with the cursor `c<n>`."""
    answers = []
    for index, page in enumerate(nodes):
        more = index + 1 < len(nodes)
        info = {"hasNextPage": more, "endCursor": f"c{index + 1}" if more else None}
        data: dict = {connection: {"pageInfo": info, "nodes": page}}
        for key in reversed(path):
            data = {key: data}
        answers.append(ok({"data": {"repository": data}}))
    return answers


def issue_pages(*nodes: list[dict]) -> list[dict]:
    return pages(("milestone",), "issues", *nodes)


def closing_pages(*nodes: list[dict]) -> list[dict]:
    return pages(("pullRequest",), "closingIssuesReferences", *nodes)


class Gate:
    """What a run of the step gave: its exit code, its sentence, its outputs and the calls of gh."""

    def __init__(self, done: subprocess.CompletedProcess[str], tmp_path: Path) -> None:
        self.code = done.returncode
        self.summary = (tmp_path / "summary.md").read_text()
        self.out = self.summary + done.stdout + done.stderr
        self.log = done.stdout
        lines = (tmp_path / "output.txt").read_text().splitlines()
        self.outputs = dict(line.split("=", 1) for line in lines)
        calls = tmp_path / "bin" / "calls"
        logged = calls.read_text().splitlines() if calls.exists() else []
        self.calls = [json.loads(line) for line in logged]

    def kinds(self) -> list[str]:
        """The calls of gh by their kind, in order."""
        kinds = []
        for call in self.calls:
            if call[1] != "graphql":
                kinds.append("pulls")
            else:
                query = next(arg for arg in call if arg.startswith("query="))
                kinds.append("closing" if "closingIssuesReferences" in query else "issues")
        return kinds


def gate_env(
    tmp_path: Path,
    *,
    event: str = "push",
    ref: str = "refs/heads/main",
    default: str = "main",
    sha: str = SHA,
    answers: dict | None = None,
) -> dict[str, str]:
    """The environment of the step: the job's as the runner gives it, with the script's checkout
    in `.sdk-gates` and the stub `gh` first on the path, and the values of its `env:` block."""
    workspace = tmp_path / "workspace"
    script = workspace / ".sdk-gates" / "scripts" / "conventions.py"
    if not script.exists():
        script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, script)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "calls").unlink(missing_ok=True)
    (bin_dir / "gh").write_text(f"#!{sys.executable}\n{STUB}")
    (bin_dir / "gh").chmod(0o755)
    (bin_dir / "answers.json").write_text(json.dumps(answers or {}))
    (tmp_path / "summary.md").write_text("")
    (tmp_path / "output.txt").write_text("")
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "EVENT": event,
        "SHA": sha,
        "REPO": REPO,
        "REF": ref,
        "DEFAULT_BRANCH": default,
        "GH_TOKEN": "the-workflow-token",
    }


def run_gate(
    tmp_path: Path,
    *,
    pulls: list[dict] | None = None,
    issues: list[dict] | None = None,
    closes: list[dict] | None = None,
    more: dict[str, str] | None = None,
    **kwargs: str,
) -> Gate:
    """Run the step `Gate` as the runner's default shell runs it, in the workspace; `more`
    changes or adds to its environment."""
    answers = {
        "pulls": [ok([pull()])] if pulls is None else pulls,
        "issues": issue_pages([issue(12)]) if issues is None else issues,
        "closing": closing_pages([closing(12)]) if closes is None else closes,
    }
    env = {**gate_env(tmp_path, answers=answers, **kwargs), **(more or {})}
    done = subprocess.run(
        [BASH, "-e", "-o", "pipefail", "-c", step("Gate")],
        env=env,
        cwd=env["GITHUB_WORKSPACE"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Gate(done, tmp_path)


def judged(gate: Gate, pr: str = "7") -> None:
    assert (gate.code, gate.outputs) == (0, {"run": "true", "pr": pr}), gate.out
    assert "range gate: the range is judged, since " in gate.out


def not_judged(gate: Gate, pr: str = "7") -> None:
    assert (gate.code, gate.outputs) == (0, {"run": "false", "pr": pr}), gate.out
    assert "range gate: no run, since " in gate.out


def one_sentence(gate: Gate) -> str:
    """The gate's one sentence, which goes to the log and to the job summary alike."""
    lines = gate.summary.splitlines()
    assert len(lines) == 1, gate.summary
    assert gate.log.splitlines() == lines
    return lines[0]


# --- a push ------------------------------------------------------------------------------


def test_the_step_is_one_call_of_the_script() -> None:
    assert step("Gate") == CALL


def test_the_last_step_that_the_pull_request_closes_lets_the_range_be_judged(
    tmp_path: Path,
) -> None:
    """The answer still shows the step open, seconds after the merge: it counts as closed."""
    gate = run_gate(tmp_path)
    judged(gate)
    assert one_sentence(gate) == (
        "range gate: the range is judged, since #7 closes the last open step #12 of the "
        "milestone `sdk-usda-psd 0.5.0`."
    )
    assert gate.kinds() == ["pulls", "issues", "closing"]


def test_the_last_steps_that_the_pull_request_closes_are_named(tmp_path: Path) -> None:
    gate = run_gate(
        tmp_path,
        issues=issue_pages([issue(14), issue(12), issue(20, "gap")]),
        closes=closing_pages([closing(12), closing(14), closing(30)]),
    )
    judged(gate)
    assert "#7 closes the last open steps #12 and #14 of the milestone" in gate.out


def test_an_open_step_that_the_pull_request_does_not_close_is_named(tmp_path: Path) -> None:
    gate = run_gate(
        tmp_path,
        issues=issue_pages([issue(12), issue(15), issue(13)]),
        closes=closing_pages([closing(12)]),
    )
    not_judged(gate)
    assert one_sentence(gate) == (
        "range gate: no run, since the milestone `sdk-usda-psd 0.5.0` keeps the open steps #13 "
        "and #15, which #7 does not close."
    )


def test_one_open_step_left_is_named(tmp_path: Path) -> None:
    gate = run_gate(
        tmp_path,
        issues=issue_pages([issue(12), issue(13)]),
        closes=closing_pages([closing(12)]),
    )
    not_judged(gate)
    assert "keeps the open step #13, which #7 does not close." in gate.out


def test_a_milestone_with_no_open_step_lets_the_range_be_judged(tmp_path: Path) -> None:
    """Every step closed before, and other issues open: the closing issues are not read."""
    gate = run_gate(tmp_path, issues=issue_pages([issue(20, "gap"), issue(21, "change")]))
    judged(gate)
    assert "the milestone `sdk-usda-psd 0.5.0` of #7 has no open step." in gate.out
    assert gate.kinds() == ["pulls", "issues"]


def test_an_empty_milestone_lets_the_range_be_judged(tmp_path: Path) -> None:
    judged(run_gate(tmp_path, issues=issue_pages([])))


@pytest.mark.parametrize("title", ["0.7.4 Release", " 0.7.4 Release "])
def test_a_release_pr_by_its_title_is_not_judged(tmp_path: Path, title: str) -> None:
    """Its own review judged it; nothing of the milestone is read."""
    gate = run_gate(tmp_path, pulls=[ok([pull(title=title)])])
    not_judged(gate)
    assert "since #7 is a release PR, which its own review judged." in gate.out
    assert gate.kinds() == ["pulls"]


@pytest.mark.parametrize("labels", [("release",), ("bug", "Release")])
def test_a_release_pr_by_its_label_is_not_judged(tmp_path: Path, labels: tuple[str, ...]) -> None:
    gate = run_gate(tmp_path, pulls=[ok([pull(title="Ship the next version", labels=labels)])])
    not_judged(gate)
    assert "since #7 is a release PR" in gate.out
    assert gate.kinds() == ["pulls"]


def test_a_pull_request_without_a_milestone_is_not_judged(tmp_path: Path) -> None:
    gate = run_gate(tmp_path, pulls=[ok([pull(milestone=None)])])
    not_judged(gate)
    assert one_sentence(gate) == "range gate: no run, since #7 carries no milestone."
    assert gate.kinds() == ["pulls"]


@pytest.mark.parametrize(
    "pulls",
    [
        [],
        [pull(merged=False)],
        [pull(merge_sha=OTHER_SHA)],
        [pull(3, merged=False), pull(4, merge_sha=OTHER_SHA)],
    ],
    ids=["none", "open", "another merge commit", "neither"],
)
def test_a_push_that_no_pull_requests_merge_made_is_not_judged(
    tmp_path: Path, pulls: list[dict]
) -> None:
    """A commit's pull requests include the open ones that hold it: only the merged one whose
    merge commit is the pushed commit made it."""
    gate = run_gate(tmp_path, pulls=[ok(pulls)])
    not_judged(gate, pr="")
    assert one_sentence(gate) == (
        f"range gate: no run, since no pull request's merge made the commit {SHA[:7]}."
    )
    assert gate.kinds() == ["pulls"]


def test_the_merged_pull_request_is_found_among_the_commits_others(tmp_path: Path) -> None:
    gate = run_gate(tmp_path, pulls=[ok([pull(3, merged=False), pull(9), pull(4, merged=False)])])
    judged(gate, pr="9")


@pytest.mark.parametrize(
    ("ref", "default"),
    [("refs/heads/release/0.7", "main"), ("refs/tags/v0.7.4", "main"), ("refs/heads/main", "")],
)
def test_a_push_to_another_branch_is_not_judged(tmp_path: Path, ref: str, default: str) -> None:
    gate = run_gate(tmp_path, ref=ref, default=default)
    not_judged(gate, pr="")
    assert f"since the push is to `{ref}` and not to the default branch `{default}`." in gate.out
    assert gate.calls == []


def test_the_default_branch_is_the_repositorys(tmp_path: Path) -> None:
    judged(run_gate(tmp_path, ref="refs/heads/trunk", default="trunk"))


@pytest.mark.parametrize("event", ["schedule", "pull_request", ""])
def test_another_event_is_not_judged(tmp_path: Path, event: str) -> None:
    gate = run_gate(tmp_path, event=event)
    not_judged(gate, pr="")
    assert "is neither a push nor a dispatch." in gate.out
    assert gate.calls == []


# --- a dispatch --------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/release/0.7"])
def test_a_dispatch_always_lets_the_range_be_judged_and_names_the_pull_request(
    tmp_path: Path, ref: str
) -> None:
    """An open step, a release PR and no milestone alike: a dispatch reads nothing but the
    pull request, for the comment of step 3.1."""
    gate = run_gate(
        tmp_path,
        event="workflow_dispatch",
        ref=ref,
        pulls=[ok([pull(title="0.7.4 Release", milestone=None)])],
    )
    judged(gate)
    assert one_sentence(gate) == (
        "range gate: the range is judged, since a dispatch always judges it; #7 merged the "
        f"commit {SHA[:7]}."
    )
    assert gate.kinds() == ["pulls"]


def test_a_dispatch_without_a_pull_request_lets_the_range_be_judged(tmp_path: Path) -> None:
    gate = run_gate(tmp_path, event="workflow_dispatch", pulls=[ok([pull(merged=False)])])
    judged(gate, pr="")
    assert one_sentence(gate) == (
        "range gate: the range is judged, since a dispatch always judges it; no pull request's "
        f"merge made the commit {SHA[:7]}."
    )


# --- the pages, the types and the closing issues -----------------------------------------


def test_a_milestone_of_more_than_one_page_is_read_to_its_end(tmp_path: Path) -> None:
    """A milestone of the pilot holds more than a hundred issues: an open step on the last page
    holds the range."""
    first = [issue(n, "gap") for n in range(100, 200)]
    gate = run_gate(
        tmp_path,
        issues=issue_pages(first, [issue(12), issue(250, "change")], [issue(260)]),
        closes=closing_pages([closing(12)]),
    )
    not_judged(gate)
    assert "keeps the open step #260, which #7 does not close." in gate.out
    assert gate.kinds() == ["pulls", "issues", "issues", "issues", "closing"]
    cursors = [
        next((arg for arg in call if arg.startswith("cursor=")), None) for call in gate.calls[1:4]
    ]
    assert cursors == [None, "cursor=c1", "cursor=c2"]


def test_the_closing_issues_of_more_than_one_page_are_read_to_their_end(tmp_path: Path) -> None:
    gate = run_gate(
        tmp_path,
        issues=issue_pages([issue(12), issue(13)]),
        closes=closing_pages([closing(n) for n in range(200, 300)], [closing(13), closing(12)]),
    )
    judged(gate)
    assert gate.kinds() == ["pulls", "issues", "closing", "closing"]


def test_the_commits_pull_requests_of_more_than_one_page_are_read_on(tmp_path: Path) -> None:
    first = [pull(n, merged=False) for n in range(100, 200)]
    gate = run_gate(tmp_path, pulls=[ok(first), ok([pull(9)])])
    judged(gate, pr="9")
    assert gate.kinds()[:2] == ["pulls", "pulls"]
    assert gate.calls[1][1].endswith("&page=2")


def test_an_issue_of_another_repository_that_the_pull_request_closes_does_not_count(
    tmp_path: Path,
) -> None:
    """A pull request may close an issue of another repository whose number is a step's here."""
    gate = run_gate(tmp_path, closes=closing_pages([closing(12, "xippios/coordinate-core")]))
    not_judged(gate)
    assert "keeps the open step #12, which #7 does not close." in gate.out


@pytest.mark.parametrize(
    "title",
    [
        "0.5.0 Step 4: A run judges only what came after",
        "0.5.0 Step 3.1: The run on the range judges and reports",
        "12.0.10 Step 10: A step",
    ],
)
def test_an_issue_with_no_type_and_a_step_title_is_a_step(tmp_path: Path, title: str) -> None:
    """Where a token reads no type, the title holds the gate: a package never looks complete
    because the types were not read."""
    gate = run_gate(tmp_path, issues=issue_pages([issue(12), issue(13, None, title)]))
    not_judged(gate)
    assert "keeps the open step #13, which #7 does not close." in gate.out


@pytest.mark.parametrize(
    "title",
    [
        "0.5.0 Package: Judge each thing where it can still be mended",
        "The mark of an unread head tree names the wrong head",
        "0.5.0 Step 3.1.2: Too many numbers",
        "0.5.0 Step 3 without a colon",
        "Step 3: No version",
        "0.5 Step 3: A short version",
        "0.5.0 step 3: The word in lowercase",
        "0.7.4 Release",
    ],
)
def test_an_issue_with_no_type_and_another_title_is_no_step(tmp_path: Path, title: str) -> None:
    gate = run_gate(tmp_path, issues=issue_pages([issue(12), issue(13, None, title)]))
    judged(gate)


@pytest.mark.parametrize("kind", ["Step", "STEP", "step"])
def test_the_type_is_read_without_case(tmp_path: Path, kind: str) -> None:
    gate = run_gate(tmp_path, issues=issue_pages([issue(12), issue(13, kind)]))
    not_judged(gate)
    assert "keeps the open step #13" in gate.out


@pytest.mark.parametrize("kind", ["gap", "change", "package", "Steps"])
def test_an_issue_of_another_type_is_no_step_whatever_its_title(tmp_path: Path, kind: str) -> None:
    gate = run_gate(tmp_path, issues=issue_pages([issue(12), issue(13, kind)]))
    judged(gate)


# --- an error fails closed ---------------------------------------------------------------

HTTP_403 = {"exit": 1, "stderr": "gh: Resource not accessible by integration (HTTP 403)\n"}
NO_STATUS = {"exit": 4, "stderr": "gh: something went wrong\n"}
UNPARSED = {"stdout": "<html>not json</html>"}
GRAPHQL_ERRORS = {
    "exit": 1,
    "stdout": json.dumps({"errors": [{"type": "FORBIDDEN", "message": "a secret text"}]}),
    "stderr": "gh: a secret text\n",
}
# GraphQL errors in an answer that gh ends without an error.
GRAPHQL_ERRORS_EXIT_0 = {"stdout": json.dumps({"data": None, "errors": [{"message": "x"}]})}
FAILURES = {
    "HTTP 403": HTTP_403,
    "gh exited 4": NO_STATUS,
    "an answer that does not parse": UNPARSED,
}
GRAPHQL_FAILURES = {"GraphQL FORBIDDEN": GRAPHQL_ERRORS, "GraphQL error": GRAPHQL_ERRORS_EXIT_0}
CALLS = {
    "pulls": "the pull requests of the commit",
    "issues": "the open issues of the milestone",
    "closing": "the closing issues of #7",
}
# Each call with each error it can end with: the REST call of the pull requests, and the two
# GraphQL calls, which can also answer with errors.
ERRORS = [(kind, error) for kind in CALLS for error in FAILURES] + [
    (kind, error) for kind in ("issues", "closing") for error in GRAPHQL_FAILURES
]


def failing(kind: str, page: dict) -> dict[str, list[dict]]:
    """The answers of a run in which the call of `kind` fails with `page`, the others served:
    the keywords of `run_gate`."""
    answers = {
        "pulls": [ok([pull()])],
        "issues": issue_pages([issue(12)]),
        "closes": closing_pages([closing(12)]),
    }
    answers["closes" if kind == "closing" else kind] = [page]
    return answers


def failed(gate: Gate, call: str, kind: str) -> None:
    """The run failed closed: exit 1, `run` never `true`, and one line that names the call and
    the class of the error and never the message of the upstream."""
    assert gate.code == 1, gate.out
    assert gate.outputs.get("run") != "true"
    assert one_sentence(gate) == f"range gate: no run, since reading {call} failed: {kind}."
    assert "secret text" not in gate.out


@pytest.mark.parametrize(("kind", "error"), ERRORS)
def test_an_error_of_a_call_fails_closed(tmp_path: Path, kind: str, error: str) -> None:
    gate = run_gate(tmp_path, **failing(kind, {**FAILURES, **GRAPHQL_FAILURES}[error]))
    failed(gate, CALLS[kind], error)


@pytest.mark.parametrize("error", list(FAILURES))
def test_an_error_on_a_dispatch_fails_closed_too(tmp_path: Path, error: str) -> None:
    gate = run_gate(tmp_path, event="workflow_dispatch", pulls=[FAILURES[error]])
    failed(gate, CALLS["pulls"], error)


NO_PAGE_INFO = {"pullRequest": {"closingIssuesReferences": {"nodes": []}}}
SHAPES = {
    "an object for the list of pull requests": ("pulls", ok({"message": "an object"})),
    "a pull request without its number": (
        "pulls",
        ok([{"merged_at": "x", "merge_commit_sha": SHA}]),
    ),
    "a milestone that the answer does not hold": (
        "issues",
        ok({"data": {"repository": {"milestone": None}}}),
    ),
    "an issue without its number": ("issues", issue_pages([{"title": "x", "issueType": None}])[0]),
    "a type without its name": (
        "issues",
        issue_pages([{"number": 3, "title": "x", "issueType": {}}])[0],
    ),
    "a page without its page info": ("closing", ok({"data": {"repository": NO_PAGE_INFO}})),
}


@pytest.mark.parametrize("case", list(SHAPES))
def test_an_answer_of_another_shape_fails_closed(tmp_path: Path, case: str) -> None:
    kind, page = SHAPES[case]
    gate = run_gate(tmp_path, **failing(kind, page))
    failed(gate, CALLS[kind], "an answer of another shape")


def test_a_page_that_names_a_next_page_without_a_cursor_fails_closed(tmp_path: Path) -> None:
    info = {"hasNextPage": True, "endCursor": None}
    page = ok({"data": {"repository": {"milestone": {"issues": {"pageInfo": info, "nodes": []}}}}})
    gate = run_gate(tmp_path, issues=[page])
    failed(gate, CALLS["issues"], "an answer of another shape")


# --- the page cap, the time limits and a gh that does not run (the review of .github#130) --


def numbered(count: int) -> list[list[dict]]:
    """`count` pages of the milestone's issues, one issue that is no step on each."""
    return [[issue(1000 + index, "gap")] for index in range(count)]


def test_a_milestone_of_more_than_fifty_pages_fails_closed(tmp_path: Path) -> None:
    """Decision 5: the fiftieth page still names a next one, and the gate reads no further."""
    gate = run_gate(tmp_path, issues=issue_pages(*numbered(51)))
    failed(gate, CALLS["issues"], "more than 50 pages")
    assert gate.kinds().count("issues") == 50


def test_a_milestone_that_ends_on_its_fiftieth_page_is_read(tmp_path: Path) -> None:
    pages_of_issues = [*numbered(49), [issue(12)]]
    judged(run_gate(tmp_path, issues=issue_pages(*pages_of_issues)))


def test_closing_issues_of_more_than_fifty_pages_fail_closed(tmp_path: Path) -> None:
    closes = closing_pages(*[[closing(2000 + index)] for index in range(51)])
    gate = run_gate(tmp_path, closes=closes)
    failed(gate, CALLS["closing"], "more than 50 pages")


def unmerged(count: int, start: int = 0) -> list[dict]:
    """`count` pull requests of the commit that are open, the least an answer holds of each."""
    return [
        {"number": 100 + start + index, "merged_at": None, "merge_commit_sha": None}
        for index in range(count)
    ]


def test_fifty_full_pages_of_the_commits_pull_requests_fail_closed(tmp_path: Path) -> None:
    pulls = [ok(unmerged(100, 100 * page)) for page in range(51)]
    gate = run_gate(tmp_path, pulls=pulls)
    failed(gate, CALLS["pulls"], "more than 50 pages")
    assert gate.kinds() == ["pulls"] * 50


def test_a_merged_pull_request_on_the_fiftieth_page_is_read(tmp_path: Path) -> None:
    pulls = [*(ok(unmerged(100, 100 * page)) for page in range(49)), ok([pull(9)])]
    judged(run_gate(tmp_path, pulls=pulls), pr="9")


def test_a_gh_that_does_not_run_fails_closed(tmp_path: Path) -> None:
    """No `gh` on the path: the runner's `python3` alone, by a link in a directory of its own."""
    alone = tmp_path / "alone"
    alone.mkdir()
    (alone / "python3").symlink_to(sys.executable)
    gate = run_gate(tmp_path, more={"PATH": str(alone)})
    failed(gate, CALLS["pulls"], "gh did not run (FileNotFoundError)")


# The limits the tests set in place of the gate's own, so that the suite stays fast.
CALL_LIMIT = "RANGE_GATE_CALL_SECONDS"
TOTAL_LIMIT = "RANGE_GATE_SECONDS"


@pytest.mark.parametrize("kind", list(CALLS))
def test_a_call_that_does_not_come_back_fails_closed_within_its_limit(
    tmp_path: Path, kind: str
) -> None:
    """A read that hangs ends the gate with its line long before the job's timeout."""
    page = failing(kind, {"sleep": 5, "stdout": "[]"})
    started = time.monotonic()
    gate = run_gate(tmp_path, more={CALL_LIMIT: "0.5"}, **page)
    assert time.monotonic() - started < 4
    failed(gate, CALLS[kind], "gh gave no answer within 0.5 seconds")


def test_the_gate_as_a_whole_cannot_outlast_its_time(tmp_path: Path) -> None:
    """Each call within its own limit, and the pages together past the gate's: the read that
    the time runs out in fails closed, and no further page is read."""
    pulls = [{**ok(unmerged(100, 100 * page)), "sleep": 0.4} for page in range(10)]
    started = time.monotonic()
    gate = run_gate(tmp_path, pulls=pulls, more={TOTAL_LIMIT: "1.5"})
    assert time.monotonic() - started < 4
    failed(gate, CALLS["pulls"], "the gate's time ran out after 1.5 seconds")
    assert len(gate.calls) < 10


def test_the_gates_limits_stay_far_below_the_jobs_timeout() -> None:
    """The job times out after 5 minutes, its checkout included: the gate's reads end with its
    line a minute before, and one call takes at most a part of that."""
    job = WORKFLOW.split("\n  gate:\n", 1)[1].split("\n  range:\n", 1)[0]
    assert "\n    timeout-minutes: 5\n" in job
    assert fr.GATE_SECONDS == 240
    assert fr.GATE_CALL_SECONDS == 30
    assert fr.GATE_SECONDS <= 5 * 60 - 60
    assert fr.GATE_CALL_SECONDS < fr.GATE_SECONDS


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("0.5", 0.5), ("2", 2.0), ("30", 30.0), ("31", 30.0), ("0", 30.0), ("-1", 30.0), ("x", 30.0)],
)
def test_a_limit_is_only_ever_shortened(
    monkeypatch: pytest.MonkeyPatch, value: str, seconds: float
) -> None:
    """A value above the gate's own, or one that is no positive number, counts as its own, so no
    environment lets the gate outlast the job."""
    monkeypatch.setenv(CALL_LIMIT, value)
    assert fr.gate_limit(CALL_LIMIT, fr.GATE_CALL_SECONDS) == seconds
    monkeypatch.delenv(CALL_LIMIT)
    assert fr.gate_limit(CALL_LIMIT, fr.GATE_CALL_SECONDS) == 30.0


def unwritable(tmp_path: Path) -> dict[str, str]:
    """A job summary that cannot be written: its path is a directory."""
    folder = tmp_path / "a-directory"
    folder.mkdir(exist_ok=True)
    return {"GITHUB_STEP_SUMMARY": str(folder)}


@pytest.mark.parametrize(
    "case",
    [
        {},
        {"issues": issue_pages([issue(12), issue(13)])},
        {"pulls": [ok([pull(milestone=None)])]},
        {"pulls": [HTTP_403]},
        {"event": "workflow_dispatch"},
    ],
    ids=["judged", "a step left", "no milestone", "an error", "a dispatch"],
)
def test_a_summary_that_cannot_be_written_never_leaves_run_true(tmp_path: Path, case: dict) -> None:
    """An error after the decision fails the job and never leaves `run` as `true`: the sentence
    goes first, then `pr`, and `run` last."""
    gate = run_gate(tmp_path, more=unwritable(tmp_path), **case)
    assert gate.code == 1, gate.out
    assert gate.outputs.get("run") != "true"
    assert "range gate: " in gate.log
    assert "Traceback" not in gate.out


def test_an_output_file_that_cannot_be_written_fails_the_job(tmp_path: Path) -> None:
    folder = tmp_path / "outputs"
    folder.mkdir()
    gate = run_gate(tmp_path, more={"GITHUB_OUTPUT": str(folder)})
    assert gate.code == 1
    assert "Traceback" not in gate.out


@pytest.mark.parametrize(("name", "value"), [("SHA", "c0ffee"), ("REPO", "no-owner")])
def test_an_event_that_names_no_commit_or_repository_fails_closed(
    tmp_path: Path, name: str, value: str
) -> None:
    env = gate_env(tmp_path)
    env[name] = value
    done = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step("Gate")],
        env=env,
        cwd=env["GITHUB_WORKSPACE"],
        capture_output=True,
        text=True,
        check=False,
    )
    gate = Gate(done, tmp_path)
    assert gate.code == 1
    assert gate.outputs.get("run") != "true"
    assert "range gate: no run, since the event names no repository and commit" in gate.out
    assert gate.calls == []


# --- the runner's python3 ----------------------------------------------------------------


def test_the_gate_runs_where_the_sdk_cannot_be_imported(tmp_path: Path) -> None:
    """The runner's `python3` has no `anthropic`: the gate loads on the standard library."""
    answers = {"pulls": [ok([pull()])], "issues": issue_pages([issue(12)])}
    answers["closing"] = closing_pages([closing(12)])
    env = gate_env(tmp_path, answers=answers)
    script = f"{env['GITHUB_WORKSPACE']}/.sdk-gates/scripts/conventions.py"
    done = subprocess.run(
        [sys.executable, "-I", "-c", WITHOUT_SDK, script, "range-gate"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stderr) == (0, "")
    # `run` is written last, after the sentence and `pr` (finding 3 of the review of .github#130).
    assert (tmp_path / "output.txt").read_text() == "pr=7\nrun=true\n"
