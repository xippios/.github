"""A run judges only what came after the last judged commit (step 4 of .github 0.5.0, .github#100).

A run first looks along the first parents of its head, from the head down to where its range
starts, for the newest commit that a run judged: one whose check `range / range` completed as
passed or failed and whose run's comment, the one whose hidden line names that commit, stands on
the pull request whose merge made it (.github#139), or, on a pull request, the head that its own
run before judged, where that head lies on the line. The newer of the two counts. Where that run
was ready, the run judges the commits after the commit; where it was not, it judges them too and
gives each finding of that run its state. Where no commit of the line was judged, and where the
reads of the runs before fail or outlast their limits, the run builds on none and judges the
whole range as before, and the job summary says which. The first message, the job summary and
the comment say which of the three the run did and name the commit and the run it built on.

The tests run the script's commands on real temporary git repositories, with a fake Messages
client and the stub `gh` (stub_gh.py); no test needs a key or the network."""

import json
import os
import subprocess
from pathlib import Path

import conventions as fr
import pytest
import stub_gh
from test_range_review import FakeClient, finding, message, submitted

ROOT = Path(__file__).resolve().parents[2]
REPO = "xippios/sdk-usda-psd"
OTHER_URL = "https://github.com/xippios/sdk-core/blob/main/docs/conventions.md"
README = (
    "# sdk-usda-psd\n\nA source.\n\n## Documents\n\n"
    "- sdk-usda-psd: [docs/conventions.md](docs/conventions.md) — the conventions.\n"
    f"- sdk-core: [docs/conventions.md]({OTHER_URL}) — the family's.\n"
)
LABELS = ["sdk-usda-psd: docs/conventions.md", "sdk-core: docs/conventions.md"]
FIRST_FILES = {
    "README.md": README,
    "src/pkg/mod.py": "VALUE = 1\n",
    "docs/conventions.md": "# conventions, main\n",
}
CHECK_RUNS = "check-runs?check_name=range%20%2F%20range&per_page=100"
DOCUMENT_CALL = "repos/xippios/sdk-core/contents/docs/conventions.md?ref=main"
RELEASE_TITLE = "0.2.0 Release"


# --- the repositories ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
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
    # The limits of the reads of the runs before: a test that wants one shorter sets it.
    for name in ("CONVENTIONS_LINE_CALL_SECONDS", "CONVENTIONS_LINE_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, files: dict[str, str], message_text: str) -> str:
    for path, content in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message_text)
    return git(repo, "rev-parse", "HEAD")


def merge(repo: Path, branch: str, number: int, files: dict[str, str]) -> tuple[str, str]:
    """A step's branch of one commit, merged into `main` by a merge commit: both commits."""
    git(repo, "checkout", "-q", "-b", branch, "main")
    step = commit(repo, files, f"feat: {branch}")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from {branch}", branch)
    return step, git(repo, "rev-parse", "HEAD")


def make_line(root: Path) -> tuple[Path, dict[str, str]]:
    """`main` since the release tag v0.1.0 on its first commit: three steps merged by the pull
    requests #11, #12 and #13. Returns the checkout, detached at the last merge, and the commits:
    `m1`, `m2` and `m3` the merges, `one`, `two` and `three` the steps' own commits."""
    ws = root / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    shas = {"first": commit(ws, FIRST_FILES, "feat: the first commit")}
    git(ws, "tag", "v0.1.0")
    shas["one"], shas["m1"] = merge(ws, "step-1", 11, {"src/pkg/one.py": "ONE = 1\n"})
    shas["two"], shas["m2"] = merge(ws, "step-2", 12, {"src/pkg/two.py": "TWO = 2\n"})
    shas["three"], shas["m3"] = merge(ws, "step-3", 13, {"src/pkg/three.py": "THREE = 3\n"})
    git(ws, "checkout", "-q", "--detach", shas["m3"])
    return ws, shas


def make_release(root: Path, *, rounds: int = 1) -> tuple[Path, dict[str, str]]:
    """`make_line` and a release branch from its last merge with ``rounds`` commits, `rel1` the
    first and `head` the last, checked out at the head."""
    ws, shas = make_line(root)
    git(ws, "checkout", "-q", "-b", "release", shas["m3"])
    for number in range(1, rounds + 1):
        shas[f"rel{number}"] = commit(
            ws, {"CHANGELOG.md": f"## [0.2.0]\n\n- Round {number}.\n"}, f"release: round {number}"
        )
    shas["head"] = shas[f"rel{rounds}"]
    git(ws, "checkout", "-q", "--detach", shas["head"])
    return ws, shas


# --- GitHub's answers ----------------------------------------------------------------------


def run_url(number: int) -> str:
    return f"https://github.com/{REPO}/actions/runs/{number}/job/{number + 100}"


def check(conclusion: str | None, number: int = 5, status: str = "completed") -> dict:
    """A check run `range / range` as the checks of a commit list it."""
    return {
        "id": number,
        "name": "range / range",
        "status": status,
        "conclusion": conclusion,
        "html_url": run_url(number),
    }


def merged_by(sha: str, number: int) -> dict:
    """The pull requests of ``sha``: the one whose merge made it."""
    pull = {
        "number": number,
        "merged_at": "2026-11-22T00:00:00Z",
        "merge_commit_sha": sha,
        "title": f"0.5.0 Step {number}: a step",
        "labels": [],
        "milestone": None,
    }
    return {sha: [pull]}


def range_body(sha: str, verdict: str, findings: list[dict]) -> str:
    """The comment of a run on the range up to ``sha``, as the Verdict step writes it."""
    result = {
        "verdict": verdict,
        "findings": findings,
        "range": {"kind": "range", "commit": sha, "since": "a" * 40, "tag": "v0.1.0"},
        "documents": LABELS,
    }
    return fr.verdict_comment(result, REPO, sha)[0]


def pr_body(head: str, verdict: str, findings: list[dict]) -> str:
    """The comment of a pull request's own review of ``head``."""
    result = {
        "verdict": verdict,
        "findings": findings,
        "range": {"release": True, "since": "a" * 40, "tag": "v0.1.0"},
        "documents": LABELS,
    }
    return fr.verdict_comment(result, REPO, head)[0]


def judged(sha: str, number: int, verdict: str, findings: list[dict], run: int = 5) -> dict:
    """The answers for a commit that a run on the range judged: its check, its pull request and
    the comment of that run there."""
    conclusion = "success" if verdict == "ready" else "failure"
    return {
        "checks": {sha: [check(conclusion, run)]},
        "pulls": merged_by(sha, number),
        "pr_comments": {
            str(number): [[stub_gh.comment(90 + number, range_body(sha, verdict, findings))]]
        },
    }


def answers(*parts: dict, **more) -> dict:
    """The stub's answers: the other repository's document and the parts, joined key by key."""
    joined: dict = {"document": "# conventions of sdk-core\n"}
    for part in parts:
        for key, value in part.items():
            joined[key] = {**joined.get(key, {}), **value} if isinstance(value, dict) else value
    return {**joined, **more}


@pytest.fixture
def gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install the stub `gh` first on the path with the given answers; returns its directory."""

    def install(given: dict) -> Path:
        bin_dir = stub_gh.install(tmp_path / "bin", given)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        return bin_dir

    return install


@pytest.fixture
def actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    files = {"summary": tmp_path / "summary.md", "output": tmp_path / "output.txt"}
    for path in files.values():
        path.write_text("")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(files["summary"]))
    monkeypatch.setenv("GITHUB_OUTPUT", str(files["output"]))
    return files


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-tests")

    def install(*script):
        client = FakeClient(script)
        monkeypatch.setattr(fr, "make_client", lambda *key: client)
        return client

    return install


def range_prepare(ws: Path, sha: str) -> int:
    return fr.main(
        ["range-prepare", "--repo", REPO, "--commit", sha, "--workspace", str(ws), "--main", "main"]
    )


def pull_request(comments: list[dict], title: str = RELEASE_TITLE) -> dict:
    """The pull request as `gh pr view` gives it, with the check's comments."""
    return {"title": title, "body": "Body.", "author": {"login": "opener"}, "comments": comments}


def pr_comment(body: str) -> dict:
    """A comment of the check as `gh pr view --json comments` gives it."""
    return {
        "author": {"login": "github-actions"},
        "body": body,
        "createdAt": "2026-11-22T01:00:00Z",
    }


def prepare(ws: Path, base: str, head: str, *extra: str) -> int:
    return fr.main(
        [
            "prepare",
            "--repo",
            REPO,
            "--pr",
            "7",
            "--base-sha",
            base,
            "--head-sha",
            head,
            "--workspace",
            str(ws),
            "--main",
            "main",
            *extra,
        ]
    )


def checked(bin_dir: Path) -> list[str]:
    """The commits whose checks were read, in the order of the reads."""
    return [
        call[1].split("/commits/", 1)[1].split("/", 1)[0]
        for call in stub_gh.calls(bin_dir)
        if call[0] == "api" and call[1].endswith(f"/{CHECK_RUNS}")
    ]


def meta_of(ws: Path) -> dict:
    return json.loads((ws / ".review" / "meta.json").read_text())


def summary_of(actions: dict[str, Path]) -> list[str]:
    return actions["summary"].read_text().splitlines()


def built_notice(run: str, sha: str, verdict: str, end: str) -> str:
    return (
        f"conventions: the review builds on {run}, which judged the commit {sha} {verdict}; it "
        f"judges the commits from {sha} to {end}"
    )


NONE_JUDGED = (
    "conventions: no run before judged a commit of the range; the review builds on none and "
    "judges the whole range"
)


def unread(why: str) -> str:
    return (
        f"conventions: the runs before could not be read ({why}); the review builds on none and "
        "judges the whole range"
    )


TWO = finding(file="src/pkg/two.py", line=1, blocking=True, text="Two departs.")
NOTE = finding(file="", line=None, text="A note on the range.")


# --- a run on a range ----------------------------------------------------------------------


def test_a_range_builds_on_a_passed_check_with_its_comment(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """The newest judged commit of the line counts, and the run judges what came after it alone;
    the older judged commit below it is never read."""
    ws, shas = make_line(tmp_path)
    bin_dir = gh(
        answers(
            judged(shas["m2"], 12, "ready", [NOTE]),
            judged(shas["m1"], 11, "ready", [], run=4),
        )
    )
    assert range_prepare(ws, shas["m3"]) == 0
    meta = meta_of(ws)
    assert meta["built"] == {"commit": shas["m2"], "ready": True, "run": run_url(5), "by": "range"}
    assert (meta["since"], meta["tag"], meta["unread"]) == (shas["m2"], "v0.1.0", None)
    review = ws / ".review"
    diff = (review / "diff.patch").read_text()
    assert "+THREE = 3" in diff
    assert "TWO" not in diff
    assert "ONE" not in diff
    log = (review / "log.txt").read_text()
    assert f"commit {shas['three']}\n" in log
    assert shas["two"] not in log
    assert shas["m2"] not in log
    # A ready run's findings get their states too, so they stay in the comment (fix round 1 of
    # #142); nothing up to its commit is judged again.
    assert json.loads((review / "earlier.json").read_text()) == {
        "head": shas["m2"],
        "findings": [{"number": 1, **NOTE, "file_changed": None}],
        "decisions": [],
    }
    assert checked(bin_dir) == [shas["m2"]]
    endpoints = [call[1] for call in stub_gh.calls(bin_dir)]
    assert endpoints == [
        f"repos/{REPO}/commits/{shas['m2']}/{CHECK_RUNS}",
        f"repos/{REPO}/commits/{shas['m2']}/pulls?per_page=100&page=1",
        f"repos/{REPO}/issues/12/comments?per_page=100&page=1",
        DOCUMENT_CALL,
    ]
    summary = summary_of(actions)
    notice = built_notice(f"the run {run_url(5)}", shas["m2"], "ready", f"the commit {shas['m3']}")
    assert summary[0] == notice
    assert NONE_JUDGED not in summary
    assert actions["output"].read_text() == "review=true\n"
    assert stub_gh.written(bin_dir) == []


def test_a_range_builds_on_a_failed_check_and_hands_over_its_findings(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A run that was not ready is built on too: its findings go to `earlier.json` for their
    states, each with whether its file changed since that commit, and no decision of an opener,
    since a range has no pull request (the plan's decision on a failed run on the range)."""
    ws, shas = make_line(tmp_path)
    gh(answers(judged(shas["m2"], 12, "not ready", [TWO, NOTE])))
    assert range_prepare(ws, shas["m3"]) == 0
    meta = meta_of(ws)
    assert meta["built"] == {"commit": shas["m2"], "ready": False, "run": run_url(5), "by": "range"}
    review = ws / ".review"
    earlier = json.loads((review / "earlier.json").read_text())
    assert earlier == {
        "head": shas["m2"],
        "findings": [
            {"number": 1, **TWO, "file_changed": False},
            {"number": 2, **NOTE, "file_changed": None},
        ],
        "decisions": [],
    }
    changed = json.loads((review / "changed.json").read_text())
    assert (changed["head"], changed["compared"], changed["files"]) == (
        shas["m2"],
        True,
        ["src/pkg/three.py"],
    )
    summary = summary_of(actions)
    run = f"the run {run_url(5)}"
    assert summary[0] == built_notice(run, shas["m2"], "not ready", f"the commit {shas['m3']}")
    assert f"conventions: the run before judged {shas['m2']} and gave 2 findings" in summary


def test_a_range_with_no_judged_commit_judges_the_whole_range(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    ws, shas = make_line(tmp_path)
    bin_dir = gh(answers())
    assert range_prepare(ws, shas["m3"]) == 0
    meta = meta_of(ws)
    assert (meta["built"], meta["unread"], meta["since"]) == (None, None, shas["first"])
    diff = (ws / ".review" / "diff.patch").read_text()
    for text in ("+ONE = 1", "+TWO = 2", "+THREE = 3"):
        assert text in diff
    # Every commit of the line between the tag's commit and the commit, newest first.
    assert checked(bin_dir) == [shas["m2"], shas["m1"]]
    summary = summary_of(actions)
    assert summary[0] == (
        f"conventions: the review judges the range from v0.1.0 to the commit {shas['m3']}"
    )
    assert summary[-1] == NONE_JUDGED


@pytest.mark.parametrize(
    "kind",
    [
        "skipped",
        "cancelled",
        "in progress",
        "no comment",
        "a comment of another commit",
        "the pull request's own comment",
        "no pull request",
        "a comment of another verdict",
        "another check's name",
    ],
)
def test_a_commit_whose_check_does_not_stand_for_a_judged_range_counts_for_nothing(
    tmp_path: Path, gh, actions: dict[str, Path], kind: str
) -> None:
    """A skipped check, one not completed, one without its comment, one whose comment names
    another commit or says another verdict count for nothing (.github#139): the run reads on and
    builds on the judged commit below it."""
    ws, shas = make_line(tmp_path)
    m2 = shas["m2"]
    parts = judged(m2, 12, "ready", [NOTE])
    if kind == "skipped":
        parts["checks"] = {m2: [check("skipped")]}
    elif kind == "cancelled":
        parts["checks"] = {m2: [check("cancelled")]}
    elif kind == "in progress":
        parts["checks"] = {m2: [check(None, status="in_progress")]}
    elif kind == "no comment":
        parts["pr_comments"] = {"12": [[]]}
    elif kind == "a comment of another commit":
        body = range_body(shas["m1"], "ready", [NOTE])
        parts["pr_comments"] = {"12": [[stub_gh.comment(91, body)]]}
    elif kind == "the pull request's own comment":
        body = pr_body(shas["two"], "ready", [])
        parts["pr_comments"] = {"12": [[stub_gh.comment(91, body)]]}
    elif kind == "no pull request":
        parts["pulls"] = {m2: []}
    elif kind == "a comment of another verdict":
        # A run attempted again that failed before its review, after one that was ready.
        parts["checks"] = {m2: [check("failure")]}
    else:
        parts["checks"] = {m2: [{**check("success"), "name": "conventions / conventions"}]}
    gh(answers(parts, judged(shas["m1"], 11, "ready", [], run=4)))
    assert range_prepare(ws, shas["m3"]) == 0
    built = meta_of(ws)["built"]
    assert built == {"commit": shas["m1"], "ready": True, "run": run_url(4), "by": "range"}


def test_the_newest_check_run_of_a_commit_decides(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A commit whose run was attempted again carries the newest attempt's check."""
    ws, shas = make_line(tmp_path)
    parts = judged(shas["m2"], 12, "ready", [])
    parts["checks"] = {shas["m2"]: [check("success", 9), check("failure", 3)]}
    gh(answers(parts))
    assert range_prepare(ws, shas["m3"]) == 0
    assert meta_of(ws)["built"]["run"] == run_url(9)


def test_a_head_that_does_not_descend_from_the_judged_commit_builds_on_none(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A release branch cut before the judged commit: that commit lies on no first-parent line
    of its head, and is never read."""
    ws, shas = make_line(tmp_path)
    git(ws, "checkout", "-q", "-b", "release/0.1", shas["m1"])
    fix = commit(ws, {"src/pkg/fix.py": "FIX = 1\n"}, "fix: on the branch")
    patch = commit(ws, {"src/pkg/fix.py": "FIX = 2\n"}, "fix: again")
    git(ws, "checkout", "-q", "--detach", patch)
    bin_dir = gh(answers(judged(shas["m2"], 12, "ready", []), judged(shas["m3"], 13, "ready", [])))
    assert range_prepare(ws, patch) == 0
    assert meta_of(ws)["built"] is None
    assert checked(bin_dir) == [fix, shas["m1"]]
    assert summary_of(actions)[-1] == NONE_JUDGED


def test_the_line_ends_where_it_leaves_the_descendants_of_the_tag(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """The tag on a branch that `main` merged: a commit of `main` made while the branch was open
    descends from no tag, and a run on it judged the release before: it counts for nothing."""
    ws = tmp_path / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    commit(ws, FIRST_FILES, "feat: the first commit")
    git(ws, "checkout", "-q", "-b", "release/0.1")
    commit(ws, {"CHANGELOG.md": "## [0.1.0]\n"}, "release: 0.1.0")
    git(ws, "tag", "v0.1.0")
    git(ws, "checkout", "-q", "main")
    other = commit(ws, {"src/pkg/old.py": "OLD = 1\n"}, "feat: judged for the release before")
    git(ws, "merge", "-q", "--no-ff", "-m", "Merge the release branch", "release/0.1")
    joined = git(ws, "rev-parse", "HEAD")
    _step, last = merge(ws, "step-1", 11, {"src/pkg/new.py": "NEW = 1\n"})
    git(ws, "checkout", "-q", "--detach", last)
    bin_dir = gh(answers(judged(other, 9, "ready", [])))
    assert range_prepare(ws, last) == 0
    assert meta_of(ws)["built"] is None
    assert checked(bin_dir) == [joined]


@pytest.mark.parametrize(
    ("fails", "why"),
    [
        ("every check", "reading the checks of the commit {m2} failed: HTTP 502"),
        ("the second check", "reading the checks of the commit {m1} failed: HTTP 502"),
        ("the comments", "reading the comments of #12 failed: HTTP 502"),
    ],
)
def test_reads_that_fail_build_on_none_and_say_so(
    tmp_path: Path, gh, actions: dict[str, Path], fails: str, why: str
) -> None:
    """A read that fails is no reason to fail a review: the run judges the whole range and its
    job summary says that it could not read the runs before, naming the call and the class of the
    error alone. It never builds on a commit it could not verify, the judged one below the failed
    read included."""
    ws, shas = make_line(tmp_path)
    given = answers(judged(shas["m1"], 11, "ready", []))
    if fails == "every check":
        given["checks"] = None
    elif fails == "the second check":
        given["checks"] = {shas["m1"]: None}
    else:
        given = answers(judged(shas["m2"], 12, "ready", []), pr_comments={"12": None})
    gh(given)
    assert range_prepare(ws, shas["m3"]) == 0
    reason = why.format(m1=shas["m1"][:7], m2=shas["m2"][:7])
    meta = meta_of(ws)
    assert (meta["built"], meta["unread"], meta["since"]) == (None, reason, shas["first"])
    assert summary_of(actions)[-1] == unread(reason)
    assert actions["output"].read_text() == "review=true\n"


def test_reads_that_outlast_a_calls_time_build_on_none(
    tmp_path: Path, gh, actions: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, shas = make_line(tmp_path)
    monkeypatch.setenv("CONVENTIONS_LINE_CALL_SECONDS", "0.5")
    gh(answers(sleep=2))
    assert range_prepare(ws, shas["m3"]) == 0
    why = (
        f"reading the checks of the commit {shas['m2'][:7]} failed: gh gave no answer within "
        "0.5 seconds"
    )
    assert meta_of(ws)["unread"] == why
    assert summary_of(actions)[-1] == unread(why)


def test_reads_that_outlast_their_time_together_build_on_none(
    tmp_path: Path, gh, actions: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, shas = make_line(tmp_path)
    monkeypatch.setenv("CONVENTIONS_LINE_SECONDS", "1.5")
    gh(answers(sleep=0.9))
    assert range_prepare(ws, shas["m3"]) == 0
    # Which read runs out depends on the machine's pace: the first or the second of the line.
    why = meta_of(ws)["unread"]
    assert why in {
        f"reading the checks of the commit {sha[:7]} failed: the reads of the runs before ran out "
        "of their 1.5 seconds"
        for sha in (shas["m2"], shas["m1"])
    }


def test_a_line_longer_than_its_limit_builds_on_none(
    tmp_path: Path, gh, actions: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, shas = make_line(tmp_path)
    monkeypatch.setattr(fr, "LINE_COMMITS", 1)
    bin_dir = gh(answers())
    assert range_prepare(ws, shas["m3"]) == 0
    assert meta_of(ws)["unread"] == "the line holds more than 1 commits to read"
    assert checked(bin_dir) == [shas["m2"]]


def test_the_limits_of_the_reads() -> None:
    """At most 100 commits of the line, 30 seconds a call and 120 seconds together; a variable
    shortens a limit and never lengthens it."""
    assert (fr.LINE_COMMITS, fr.LINE_CALL_SECONDS, fr.LINE_SECONDS) == (100, 30, 120)
    assert (fr.LINE_CALL_LIMIT_ENV, fr.LINE_LIMIT_ENV) == (
        "CONVENTIONS_LINE_CALL_SECONDS",
        "CONVENTIONS_LINE_SECONDS",
    )


def test_nothing_to_judge_reads_no_run_before(tmp_path: Path, gh, actions: dict[str, Path]) -> None:
    """A README that links no documents ends green before the runs before matter."""
    ws, shas = make_line(tmp_path)
    git(ws, "checkout", "-q", "main")
    git(ws, "checkout", "-q", "-b", "bare")
    last = commit(ws, {"README.md": "# sdk-usda-psd\n"}, "docs: no documents")
    git(ws, "branch", "-f", "main", last)
    git(ws, "checkout", "-q", "--detach", last)
    bin_dir = gh(answers(judged(shas["m3"], 13, "ready", [])))
    assert range_prepare(ws, last) == 0
    assert stub_gh.calls(bin_dir) == []
    assert actions["output"].read_text() == "review=false\n"


# --- the judge of a range ------------------------------------------------------------------


def built_material(tmp_path: Path, gh, verdict: str, findings: list[dict]):
    ws, shas = make_line(tmp_path)
    gh(answers(judged(shas["m2"], 12, verdict, findings)))
    assert range_prepare(ws, shas["m3"]) == 0
    return ws, shas, fr.load_material(ws, ws / ".review")


def test_the_judge_of_a_range_built_on_a_ready_run_is_told_so(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    _ws, shas, material = built_material(tmp_path, gh, "ready", [NOTE])
    assert material.built == {"commit": shas["m2"], "ready": True, "run": run_url(5), "by": "range"}
    assert [finding["text"] for finding in material.earlier.findings] == [NOTE["text"]]
    text = fr.first_message(material)["content"]
    assert text == (
        f"Review the range of {REPO} up to the commit {shas['m3']}: this review builds on the run "
        f"{run_url(5)}, which judged the commit {shas['m2']} ready, so everything up to that "
        "commit was judged and is not judged again, and the range is the commits after it, from "
        f"{shas['m2']} to the commit. It is no pull request, and the release that follows it is "
        "not in it yet. Its material is under `.review/`, the 2 documents under "
        "`.review/documents/`. Read what you need with the tools, then call `submit_verdict`. "
        "That run gave 1 finding: `.review/earlier.json` holds them, numbered from 1. Give each "
        "of them its state in `earlier`."
    )
    system = fr.system_prompt(material, fr.MAX_TURNS)
    expected = fr.RANGE_INSTRUCTIONS + fr.RANGE_BUILT_INSTRUCTIONS
    assert system[0]["text"] == expected.format(review=".review", max_turns=fr.MAX_TURNS)
    flat = " ".join(system[0]["text"].split())
    assert "Everything up to that commit was judged by that run and is not judged again" in flat


def test_the_judge_of_a_range_built_on_a_run_not_ready_gives_its_findings_their_states(
    tmp_path: Path, gh, actions: dict[str, Path], api
) -> None:
    """No finding of a range is decided, since it has no opener: the script refuses it, and the
    judge gives each finding fixed or open."""
    ws, shas, material = built_material(tmp_path, gh, "not ready", [TWO, NOTE])
    text = fr.first_message(material)["content"]
    assert text.startswith(
        f"Review the range of {REPO} up to the commit {shas['m3']}: this review builds on the run "
        f"{run_url(5)}, which judged the commit {shas['m2']} not ready, so everything"
    )
    assert text.endswith(
        " That run gave 2 findings: `.review/earlier.json` holds them, numbered from 1. Give each "
        "of them its state in `earlier`."
    )
    decided = {"number": 1, "state": "decided", "finding": None, "reason": "A reason."}
    fixed = {"number": 1, "state": "fixed", "finding": None, "reason": ""}
    still = {"number": 2, "state": "open", "finding": 1, "reason": ""}
    bad = submitted("ready", [NOTE])
    bad["input"]["earlier"] = [decided, still]
    good = submitted("ready", [NOTE])
    good["input"]["earlier"] = [fixed, still]
    client = api(message([bad]), message([good]))
    out = tmp_path / "verdict.json"
    code = fr.main(
        ["review", "--workspace", str(ws), "--review", str(ws / ".review"), "--out", str(out)]
    )
    assert code == 0
    answer = client.messages.requests[1]["messages"][-1]["content"][0]["content"]
    assert "decided needs a decision of the opener" in answer
    result = json.loads(out.read_text())
    assert [f["state"] for f in result["earlier"]["findings"]] == ["fixed", "open"]
    assert result["range"]["built"] == material.built
    assert result["range"]["unread"] is False


def test_a_range_that_builds_on_none_keeps_its_texts(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    ws, shas = make_line(tmp_path)
    gh(answers())
    assert range_prepare(ws, shas["m3"]) == 0
    material = fr.load_material(ws, ws / ".review")
    assert material.built is None
    system = fr.system_prompt(material, fr.MAX_TURNS)
    assert system[0]["text"] == fr.RANGE_INSTRUCTIONS.format(review=".review", max_turns=160)
    assert fr.first_message(material)["content"].startswith(
        f"Review the range of {REPO} up to the commit {shas['m3']}: the commits from the release "
        f"tag v0.1.0 ({shas['first']})"
    )


@pytest.mark.parametrize(
    "built",
    [
        {"commit": "c" * 7, "ready": True, "run": None, "by": "range"},
        {"commit": "c" * 40, "ready": "yes", "run": None, "by": "range"},
        {"commit": "c" * 40, "ready": True, "run": "https://example.com/run", "by": "range"},
        {"commit": "c" * 40, "ready": True, "run": None, "by": "someone"},
        {"commit": "c" * 40, "ready": True, "run": None},
        "c" * 40,
    ],
)
def test_a_meta_whose_run_built_on_does_not_read_is_no_verdict(
    tmp_path: Path, gh, actions: dict[str, Path], monkeypatch: pytest.MonkeyPatch, built
) -> None:
    ws, shas = make_line(tmp_path)
    gh(answers())
    assert range_prepare(ws, shas["m3"]) == 0
    meta_file = ws / ".review" / "meta.json"
    meta_file.write_text(json.dumps({**json.loads(meta_file.read_text()), "built": built}))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-tests")
    monkeypatch.setattr(fr, "make_client", lambda *key: pytest.fail("no client"))
    outcome = fr.review(ws, ws / ".review")
    assert outcome.verdict is None
    assert outcome.reason == ".review/meta.json names no run it builds on"


# --- the review of a pull request ----------------------------------------------------------


def test_a_release_pr_builds_on_the_judged_commit_of_its_line(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """Proof 5's case: the release PR's head descends from a commit with a passed `range / range`;
    the review judges the commits since it, and the description as on every run. The default
    branch holds the range but the release's own commit, which the first message names (step
    6.3)."""
    ws, shas = make_release(tmp_path)
    view = pull_request([])
    bin_dir = gh(answers(judged(shas["m2"], 12, "ready", []), view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    meta = meta_of(ws)
    assert meta["built"] == {"commit": shas["m2"], "ready": True, "run": run_url(5), "by": "range"}
    assert (meta["since"], meta["tag"], meta["release"]) == (shas["m2"], "v0.1.0", True)
    assert meta["own"] == [shas["head"]]
    review = ws / ".review"
    diff = (review / "diff.patch").read_text()
    assert "CHANGELOG.md" in diff
    assert "+THREE = 3" in diff
    assert "TWO" not in diff
    assert json.loads((review / "pr.json").read_text())["body"] == "Body."
    assert not (review / "earlier.json").exists()
    # The head's own commit, then the line: the last merge, then the judged one.
    assert checked(bin_dir) == [shas["m3"], shas["m2"]]
    summary = summary_of(actions)
    assert summary[0] == built_notice(f"the run {run_url(5)}", shas["m2"], "ready", "the head")
    assert "conventions: a release PR: the review judges the range from v0.1.0 to the head" not in (
        summary
    )
    material = fr.load_material(ws, review)
    text = fr.first_message(material)["content"]
    assert text == (
        f"Review the release pull request {REPO}#7: base {shas['m3']}, head {shas['head']}. It "
        f"releases version 0.2.0. This review builds on the run {run_url(5)}, which judged the "
        f"commit {shas['m2']} ready: everything up to that commit was judged and is not judged "
        f"again, so the range is the commits after it, from {shas['m2']} to the head. Its "
        "material is under `.review/`, the 2 documents under `.review/documents/`. Read what you "
        "need with the tools, then call `submit_verdict`. The default branch already holds every "
        f"commit of the range but the pull request's own: {shas['head']}."
    )
    system = fr.system_prompt(material, fr.MAX_TURNS)
    expected = fr.INSTRUCTIONS + fr.BUILT_INSTRUCTIONS
    assert system[0]["text"] == expected.format(review=".review", max_turns=fr.MAX_TURNS)
    flat = " ".join(system[0]["text"].split())
    assert "The description and the checks are judged as on every run." in flat


def test_a_release_pr_without_a_judged_commit_judges_its_whole_range(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """Proof 6's case: no commit of the line carries a judged run; the texts stay as before."""
    ws, shas = make_release(tmp_path)
    bin_dir = gh(answers(view=pull_request([])))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    meta = meta_of(ws)
    assert (meta["built"], meta["unread"], meta["since"]) == (None, None, shas["first"])
    assert checked(bin_dir) == [shas["m3"], shas["m2"], shas["m1"]]
    summary = summary_of(actions)
    assert summary[0] == (
        "conventions: a release PR: the review judges the range from v0.1.0 to the head"
    )
    assert NONE_JUDGED in summary
    material = fr.load_material(ws, ws / ".review")
    assert fr.first_message(material)["content"].startswith(
        f"Review the release pull request {REPO}#7: base {shas['m3']}, head {shas['head']}. It "
        f"releases version 0.2.0. The range is the release's, from v0.1.0 ({shas['first']})"
    )
    system = fr.system_prompt(material, fr.MAX_TURNS)
    assert system[0]["text"] == fr.INSTRUCTIONS.format(review=".review", max_turns=160)


# --- the commits that the default branch already holds (step 6.3 of .github 0.5.0) ---------


def release_text(shas: dict[str, str], base: str) -> str:
    """The first message of a release pull request that builds on nothing, before its sentence
    of the pull request's own commits."""
    return (
        f"Review the release pull request {REPO}#7: base {base}, head {shas['head']}. It releases "
        f"version 0.2.0. The range is the release's, from v0.1.0 ({shas['first']}) to the head: "
        "the pull request's own diff is the CHANGELOG and the version, and the diff prepared for "
        "you holds everything the release ships. Its material is under `.review/`, the 2 "
        "documents under `.review/documents/`. Read what you need with the tools, then call "
        "`submit_verdict`."
    )


def own_sentence(*commits: str) -> str:
    named = commits[0] if len(commits) == 1 else ", ".join(commits[:-1]) + " and " + commits[-1]
    return (
        " The default branch already holds every commit of the range but the pull request's own: "
        f"{named}."
    )


def first_text(ws: Path) -> str:
    return fr.first_message(fr.load_material(ws, ws / ".review"))["content"]


def test_an_open_release_names_its_own_commits(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A release PR with commits of its own: its range holds the steps that the default branch
    merged since the tag and the release's own commits, and the first message names the latter,
    so the judge tells a commit that no later commit mends from one it can still change
    (.github#152)."""
    ws, shas = make_release(tmp_path, rounds=2)
    gh(answers(view=pull_request([])))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    meta = meta_of(ws)
    assert (meta["since"], meta["built"]) == (shas["first"], None)
    assert meta["own"] == [shas["rel2"], shas["rel1"]]
    assert first_text(ws) == release_text(shas, shas["m3"]) + (
        " The default branch already holds every commit of the range but the pull request's own: "
        f"{shas['rel2']} and {shas['rel1']}."
    )
    # Where git names no merge base, as without the default branch, nothing is named.
    assert fr.own_commits(ws, "no-such-branch", "no-base", shas["first"], shas["head"]) is None


def test_an_open_release_names_the_same_commits_after_the_default_branch_moved_on(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A step merged after the release branch was cut is in neither the range nor the list."""
    ws, shas = make_release(tmp_path, rounds=2)
    shas["four"], shas["m4"] = merge(ws, "step-4", 14, {"src/pkg/four.py": "FOUR = 4\n"})
    git(ws, "checkout", "-q", "--detach", shas["head"])
    gh(answers(view=pull_request([])))
    assert prepare(ws, shas["m4"], shas["head"], "--release") == 0
    assert meta_of(ws)["own"] == [shas["rel2"], shas["rel1"]]
    assert first_text(ws) == release_text(shas, shas["m4"]) + own_sentence(
        shas["rel2"], shas["rel1"]
    )


def test_a_release_branch_that_merged_the_default_branch_names_its_commit_below_the_merge(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """The release branch holds `rel1`, then a merge of the default branch at `m4`, then `rel2`:
    `rel1` lies below that merge in the log, and it is named as the pull request's own all the
    same, with the merge itself (finding 3 of the review of #154)."""
    ws, shas = make_line(tmp_path)
    git(ws, "checkout", "-q", "-b", "release", shas["m3"])
    shas["rel1"] = commit(ws, {"CHANGELOG.md": "## [0.2.0]\n\n- Round 1.\n"}, "release: round 1")
    shas["four"], shas["m4"] = merge(ws, "step-4", 14, {"src/pkg/four.py": "FOUR = 4\n"})
    git(ws, "checkout", "-q", "release")
    git(ws, "merge", "-q", "--no-ff", "-m", "Merge branch 'main' into release", "main")
    shas["mm"] = git(ws, "rev-parse", "HEAD")
    shas["rel2"] = commit(ws, {"CHANGELOG.md": "## [0.2.0]\n\n- Round 2.\n"}, "release: round 2")
    shas["head"] = shas["rel2"]
    git(ws, "checkout", "-q", "--detach", shas["head"])
    gh(answers(view=pull_request([])))
    assert prepare(ws, shas["m4"], shas["head"], "--release") == 0
    own = meta_of(ws)["own"]
    assert own == [shas["rel2"], shas["mm"], shas["rel1"]]
    for held in ("m4", "four", "m3", "three"):
        assert shas[held] not in own
    # `rel1` does not come after the merge base `m4`: "the commits after it" would miss it.
    below = ["git", "-C", str(ws), "merge-base", "--is-ancestor", shas["m4"], shas["rel1"]]
    assert subprocess.run(below, check=False).returncode == 1
    assert first_text(ws) == release_text(shas, shas["m4"]) + own_sentence(*own)


def merged_release(root: Path) -> tuple[Path, dict[str, str]]:
    """`make_release` whose pull request merged into `main` by a merge commit `mr`."""
    ws, shas = make_release(root)
    git(ws, "checkout", "-q", "main")
    git(ws, "merge", "-q", "--no-ff", "-m", "Merge pull request #7 from release", "release")
    shas["mr"] = git(ws, "rev-parse", "HEAD")
    git(ws, "checkout", "-q", "--detach", shas["head"])
    return ws, shas


@pytest.mark.parametrize("main", ["main", "base"], ids=["the default branch", "--main at its base"])
def test_a_merged_release_names_what_the_open_one_was_told(
    tmp_path: Path, gh, actions: dict[str, Path], main: str
) -> None:
    """The default branch holds the head of a merged release: its own commits are read from the
    merge base of its base and its head, as a dry run of proof 8 meets them (finding 2 of the
    review of #154), and `--main` at its base tells the same."""
    ws, shas = merged_release(tmp_path)
    gh(answers(view=pull_request([])))
    extra = ("--main", shas["m3"]) if main == "base" else ()
    assert prepare(ws, shas["m3"], shas["head"], "--release", *extra) == 0
    assert meta_of(ws)["own"] == [shas["head"]]
    assert first_text(ws) == release_text(shas, shas["m3"]) + own_sentence(shas["head"])


def test_a_pull_request_whose_base_holds_its_head_says_that_none_is_its_own(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """Where the base read after the merge holds the head as the default branch does, every
    commit of the range is one that the default branch holds, and the first message says so."""
    ws, shas = merged_release(tmp_path)
    gh(answers(view=pull_request([])))
    assert prepare(ws, shas["mr"], shas["head"], "--release") == 0
    assert meta_of(ws)["own"] == []
    assert first_text(ws) == release_text(shas, shas["mr"]) + (
        " The default branch already holds every commit of the range, so none of them is the pull "
        "request's own."
    )


def test_a_pull_request_that_is_no_release_names_no_commit_of_the_default_branch(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """Its range is its own, from the merge base: the default branch holds none of it, and the
    first message is word for word as before."""
    ws, shas = make_release(tmp_path)
    gh(answers(view=pull_request([], title="feat: a change")))
    assert prepare(ws, shas["m3"], shas["head"]) == 0
    meta = meta_of(ws)
    assert (meta["since"], meta["release"], meta["own"]) == (shas["m3"], False, None)
    text = first_text(ws)
    assert text == fr.FIRST_MESSAGE.format(
        repo=REPO,
        pr=7,
        base=shas["m3"],
        head=shas["head"],
        review=".review",
        documents="2 documents",
    )
    assert "default branch" not in text


def test_a_patch_release_against_a_release_branch_names_no_commit(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A release branch cut at the tag, a step merged there and the patch release on it: the
    default branch holds none of the range, so every commit of it reads as the pull request's
    own, by the letter of .github#152, which names the default branch (finding 6 of the review
    of #154, left to the human)."""
    ws, shas = make_line(tmp_path)
    git(ws, "checkout", "-q", "-b", "release-0.1", shas["first"])
    git(ws, "checkout", "-q", "-b", "patch-1", "release-0.1")
    shas["p1"] = commit(ws, {"src/pkg/mod.py": "VALUE = 3\n"}, "fix: a patch")
    git(ws, "checkout", "-q", "release-0.1")
    git(ws, "merge", "-q", "--no-ff", "-m", "Merge pull request #21 from patch-1", "patch-1")
    shas["pm1"] = git(ws, "rev-parse", "HEAD")
    git(ws, "checkout", "-q", "-b", "patch-release")
    shas["head"] = commit(ws, {"CHANGELOG.md": "## [0.1.1]\n\n- The patch.\n"}, "release: 0.1.1")
    git(ws, "checkout", "-q", "--detach", shas["head"])
    gh(answers(view=pull_request([], title="0.1.1 Release")))
    assert prepare(ws, shas["pm1"], shas["head"], "--release") == 0
    meta = meta_of(ws)
    assert (meta["since"], meta["own"]) == (shas["first"], None)
    assert "default branch" not in first_text(ws)


def test_main_at_the_last_release_tag_names_no_commit_on_an_open_release(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """`--main` stands for the default branch: at the last release tag it holds no commit of the
    range, so nothing is named (finding 5 of the review of #154)."""
    ws, shas = make_release(tmp_path)
    gh(answers(view=pull_request([])))
    assert prepare(ws, shas["m3"], shas["head"], "--release", "--main", "v0.1.0") == 0
    assert meta_of(ws)["own"] is None
    assert first_text(ws) == release_text(shas, shas["m3"])


def test_a_release_pr_that_builds_on_the_last_merge_names_no_commit_of_the_default_branch(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A run that builds on the last merge of the default branch judges the pull request's own
    commits alone: its first message names no commit of the default branch."""
    ws, shas = make_release(tmp_path)
    gh(answers(judged(shas["m3"], 13, "ready", []), view=pull_request([])))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    meta = meta_of(ws)
    assert (meta["since"], meta["built"]["commit"], meta["own"]) == (shas["m3"], shas["m3"], None)
    text = first_text(ws)
    assert text.startswith(f"Review the release pull request {REPO}#7: ")
    assert text.endswith("Read what you need with the tools, then call `submit_verdict`.")
    assert "default branch" not in text


@pytest.mark.parametrize("count", [20, 21])
def test_more_own_commits_than_the_message_names_are_left_to_meta_json(
    tmp_path: Path, gh, actions: dict[str, Path], count: int
) -> None:
    """Up to 20 commits are named one by one; more are counted, and `meta.json`, which the judge
    can read, lists them under `own`."""
    ws, shas = make_release(tmp_path)
    gh(answers(view=pull_request([])))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    own = [f"{n:040x}" for n in range(1, count + 1)]
    (ws / ".review" / "meta.json").write_text(json.dumps({**meta_of(ws), "own": own}))
    text = first_text(ws)
    if count > 20:
        assert text == release_text(shas, shas["m3"]) + (
            " The default branch already holds every commit of the range but the pull request's "
            f"own {count} commits, which `.review/meta.json` lists under `own`."
        )
    else:
        assert text == release_text(shas, shas["m3"]) + own_sentence(*own)


@pytest.mark.parametrize("own", ["not a list", 7, [7], ["not a commit"], [""], {"a": "b"}])
def test_own_commits_outside_their_form_are_refused(
    tmp_path: Path, gh, actions: dict[str, Path], own: object
) -> None:
    ws, shas = make_release(tmp_path)
    gh(answers(view=pull_request([])))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    meta_file = ws / ".review" / "meta.json"
    meta_file.write_text(json.dumps({**meta_of(ws), "own": own}))
    with pytest.raises(fr.PrepareError, match="names no commits of the pull request's own"):
        fr.load_material(ws, ws / ".review")


def test_a_pull_requests_own_run_before_on_the_line_is_built_on(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """The head the run before judged lies on the line, not ready: the run judges the commits
    after it and gives that run's findings their states, with the opener's decisions; no check
    of the line is read, since nothing below that head can be newer."""
    ws, shas = make_release(tmp_path, rounds=2)
    before = finding(file="CHANGELOG.md", line=1, blocking=True, text="The section is thin.")
    decided = {
        "author": {"login": "opener"},
        "body": "<!-- style: comments/decisions -->\n**Decided.** Finding 1: kept.\n",
        "createdAt": "2026-11-22T02:00:00Z",
    }
    view = pull_request([pr_comment(pr_body(shas["rel1"], "not ready", [before])), decided])
    bin_dir = gh(answers(judged(shas["m2"], 12, "ready", []), view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    meta = meta_of(ws)
    assert meta["built"] == {
        "commit": shas["rel1"],
        "ready": False,
        "run": None,
        "by": "pull request",
    }
    assert meta["since"] == shas["rel1"]
    assert checked(bin_dir) == []
    review = ws / ".review"
    diff = (review / "diff.patch").read_text()
    assert "+- Round 2." in diff
    assert "THREE" not in diff
    earlier = json.loads((review / "earlier.json").read_text())
    assert earlier["head"] == shas["rel1"]
    assert earlier["findings"] == [{"number": 1, **before, "file_changed": True}]
    assert [d["body"] for d in earlier["decisions"]] == [decided["body"]]
    summary = summary_of(actions)
    assert summary[0] == built_notice(fr.OWN_RUN, shas["rel1"], "not ready", "the head")
    material = fr.load_material(ws, review)
    text = fr.first_message(material)["content"]
    assert (
        "This review builds on this pull request's run before, which judged the commit "
        f"{shas['rel1']} not ready: "
    ) in text
    assert text.endswith(
        " That run gave 1 finding: `.review/earlier.json` holds them, numbered from 1, with the "
        "opener's decisions on the pull request. Give each of them its state in `earlier`."
    )


def test_a_ready_run_before_on_the_line_hands_over_no_findings(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    ws, shas = make_release(tmp_path, rounds=2)
    view = pull_request([pr_comment(pr_body(shas["rel1"], "ready", [NOTE]))])
    gh(answers(view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    built = meta_of(ws)["built"]
    assert (built["commit"], built["ready"], built["by"]) == (shas["rel1"], True, "pull request")
    # Its finding that did not block gets its state, so it stays in the comment (fix round 1).
    earlier = json.loads((ws / ".review" / "earlier.json").read_text())
    assert (earlier["head"], [f["text"] for f in earlier["findings"]]) == (
        shas["rel1"],
        [NOTE["text"]],
    )


def test_a_run_before_off_the_line_gives_its_states_on_the_whole_range(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A rebased head descends from no head judged before: the run builds on none and judges the
    whole range, and the run before's findings get their states as since .github 0.4.0."""
    ws, shas = make_release(tmp_path)
    gone = "e" * 40
    view = pull_request([pr_comment(pr_body(gone, "not ready", [TWO]))])
    gh(answers(view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    meta = meta_of(ws)
    assert (meta["built"], meta["since"]) == (None, shas["first"])
    earlier = json.loads((ws / ".review" / "earlier.json").read_text())
    assert earlier["head"] == gone
    material = fr.load_material(ws, ws / ".review")
    assert " The run before judged head " + gone in fr.first_message(material)["content"]


def test_a_judged_commit_newer_than_the_run_before_wins(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """The newer of the two kinds counts: a commit judged by a run on the range above the head
    that the pull request's run before judged."""
    ws, shas = make_release(tmp_path, rounds=3)
    view = pull_request([pr_comment(pr_body(shas["rel1"], "not ready", [TWO]))])
    bin_dir = gh(answers(judged(shas["rel2"], 21, "ready", [], run=8), view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    built = meta_of(ws)["built"]
    assert built == {"commit": shas["rel2"], "ready": True, "run": run_url(8), "by": "range"}
    assert checked(bin_dir) == [shas["rel2"]]
    # The run built on gave no finding; the pull request's own run before keeps its states.
    earlier = json.loads((ws / ".review" / "earlier.json").read_text())
    assert (earlier["head"], [f["text"] for f in earlier["findings"]]) == (
        shas["rel1"],
        [TWO["text"]],
    )


def test_a_run_before_newer_than_a_judged_commit_wins(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    ws, shas = make_release(tmp_path, rounds=3)
    view = pull_request([pr_comment(pr_body(shas["rel2"], "ready", []))])
    bin_dir = gh(answers(judged(shas["rel1"], 21, "ready", [], run=8), view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    assert meta_of(ws)["built"]["commit"] == shas["rel2"]
    assert checked(bin_dir) == []


def test_a_run_before_on_the_head_itself_is_no_commit_to_build_on(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """A run on a head already judged, as a reopening: the head is left out of the line, so the
    run judges as before with the states of that run's findings."""
    ws, shas = make_release(tmp_path)
    view = pull_request([pr_comment(pr_body(shas["head"], "not ready", [TWO]))])
    gh(answers(view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    assert meta_of(ws)["built"] is None
    assert json.loads((ws / ".review" / "earlier.json").read_text())["head"] == shas["head"]


def test_a_pull_requests_reads_that_fail_build_on_none(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    ws, shas = make_release(tmp_path)
    gone = "e" * 40
    view = pull_request([pr_comment(pr_body(gone, "not ready", [TWO]))])
    gh(answers(view=view, checks=None))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    why = f"reading the checks of the commit {shas['m3'][:7]} failed: HTTP 502"
    meta = meta_of(ws)
    assert (meta["built"], meta["unread"]) == (None, why)
    summary = summary_of(actions)
    assert unread(why) in summary
    # The run before keeps its states on the whole range, as before this step.
    assert json.loads((ws / ".review" / "earlier.json").read_text())["head"] == gone
    assert actions["output"].read_text() == "review=true\n"


# --- the states of the runs before (fix round 1 of #142) ----------------------------------

BLOCKS = finding(file="CHANGELOG.md", line=1, blocking=True, text="The section is thin.")


def earlier_of(ws: Path) -> dict:
    return json.loads((ws / ".review" / "earlier.json").read_text())


def fields(findings: list[dict]) -> list[dict]:
    return [{key: f[key] for key in fr.FINDING_KEYS} for f in findings]


@pytest.mark.parametrize("where", ["this head", "a head off the line"])
def test_the_pull_requests_run_before_keeps_its_states_where_the_run_builds_on_the_range(
    tmp_path: Path, gh, actions: dict[str, Path], where: str
) -> None:
    """What a run builds on decides its range, never whether an earlier finding gets its state:
    the pull request's own run before, on this very head (a reopening, a run made again) or on a
    head off the line (a rebase), gives each finding a state, the blocking one too, though the
    run builds on a judged commit of the range; none leaves the comment unsaid."""
    ws, shas = make_release(tmp_path)
    head = shas["head"] if where == "this head" else "e" * 40
    view = pull_request([pr_comment(pr_body(head, "not ready", [BLOCKS]))])
    gh(answers(judged(shas["m3"], 13, "ready", []), view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    built = meta_of(ws)["built"]
    assert (built["commit"], built["by"]) == (shas["m3"], "range")
    earlier = earlier_of(ws)
    assert earlier["head"] == head
    assert fields(earlier["findings"]) == [BLOCKS]
    material = fr.load_material(ws, ws / ".review")
    assert fr.earlier_problem({"verdict": "ready", "findings": []}, material.earlier) is not None
    assert fr.first_message(material)["content"].endswith(
        f" The run before, which judged the commit {head}, gave 1 finding: `.review/earlier.json` "
        "holds them, numbered from 1, with the opener's decisions on the pull request. Give each "
        "of them its state in `earlier`."
    )


def test_a_run_built_on_the_pull_requests_own_run_before_states_its_findings_alone(
    tmp_path: Path, gh, actions: dict[str, Path]
) -> None:
    """As before: the run before on the line is the run built on, and the judged commit below it
    is never read."""
    ws, shas = make_release(tmp_path, rounds=2)
    view = pull_request([pr_comment(pr_body(shas["rel1"], "not ready", [BLOCKS]))])
    bin_dir = gh(answers(judged(shas["m2"], 12, "ready", [NOTE]), view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    assert meta_of(ws)["built"]["by"] == "pull request"
    earlier = earlier_of(ws)
    assert earlier["head"] == shas["rel1"]
    assert fields(earlier["findings"]) == [BLOCKS]
    assert all("judged" not in f for f in earlier["findings"])
    assert checked(bin_dir) == []


def test_a_ready_run_built_on_keeps_its_findings_in_the_comment_with_their_states(
    tmp_path: Path, gh, actions: dict[str, Path], api
) -> None:
    """The findings of a ready run, which did not block, stay in the comment as they were
    given, each with what became of it (finding 2 of the review of #142)."""
    ws, shas = make_release(tmp_path, rounds=2)
    view = pull_request([pr_comment(pr_body(shas["rel1"], "ready", [NOTE]))])
    gh(answers(view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    assert fields(earlier_of(ws)["findings"]) == [NOTE]
    good = submitted("ready", [])
    good["input"]["earlier"] = [{"number": 1, "state": "fixed", "finding": None, "reason": ""}]
    api(message([good]))
    out = tmp_path / "verdict.json"
    code = fr.main(
        ["review", "--workspace", str(ws), "--review", str(ws / ".review"), "--out", str(out)]
    )
    assert code == 0
    body, _ready = fr.verdict_comment(json.loads(out.read_text()), REPO, shas["head"])
    at = f"https://github.com/{REPO}/commit/{shas['rel1']}"
    assert (
        f"The run before judged {at} and gave 1 finding:\n\n"
        "1. **the pull request** A note on the range. Fixed.\n"
    ) in body


def test_two_runs_before_state_each_finding_once(
    tmp_path: Path, gh, actions: dict[str, Path], api
) -> None:
    """The run built on and the pull request's own run before are two runs: both runs' findings
    get their states, a finding that both gave once, and none is lost."""
    ws, shas = make_release(tmp_path)
    view = pull_request([pr_comment(pr_body(shas["head"], "not ready", [BLOCKS, TWO]))])
    gh(answers(judged(shas["m3"], 13, "not ready", [TWO, NOTE]), view=view))
    assert prepare(ws, shas["m3"], shas["head"], "--release") == 0
    earlier = earlier_of(ws)
    assert earlier["head"] == shas["m3"]
    assert [(f["number"], f["text"], f.get("judged")) for f in earlier["findings"]] == [
        (1, TWO["text"], None),
        (2, NOTE["text"], None),
        (3, BLOCKS["text"], shas["head"]),
    ]
    material = fr.load_material(ws, ws / ".review")
    assert material.earlier.heads == [shas["m3"], shas["m3"], shas["head"]]
    assert " The two runs before gave 3 findings: " in fr.first_message(material)["content"]
    states = [
        {"number": 1, "state": "fixed", "finding": None, "reason": ""},
        {"number": 2, "state": "fixed", "finding": None, "reason": ""},
        {"number": 3, "state": "open", "finding": 1, "reason": ""},
    ]
    # The finding that carries it blocks with the sentence it quotes (step 6 of .github 0.5.0).
    carried = {**BLOCKS, "document": LABELS[0], "quote": FIRST_FILES["docs/conventions.md"]}
    verdict = submitted("not ready", [carried])
    verdict["input"]["earlier"] = states
    api(message([verdict]))
    out = tmp_path / "verdict.json"
    code = fr.main(
        ["review", "--workspace", str(ws), "--review", str(ws / ".review"), "--out", str(out)]
    )
    assert code == 1
    result = json.loads(out.read_text())
    assert [f.get("judged") for f in result["earlier"]["findings"]] == [None, None, shas["head"]]


def test_the_comment_lists_each_run_before_under_the_commit_it_judged() -> None:
    built = {"commit": "b" * 40, "ready": False, "run": run_url(5), "by": "range"}
    range_ = {"release": True, "since": "b" * 40, "tag": "v0.1.0", "built": built, "unread": False}
    earlier = {
        "head": "b" * 40,
        "findings": [
            {**TWO, "state": "fixed", "finding": None},
            {**BLOCKS, "state": "open", "finding": 1, "judged": "d" * 40},
        ],
    }
    body = comment_of(range_, verdict="not ready", findings=[BLOCKS], earlier=earlier)
    first, second = (f"https://github.com/{REPO}/commit/{c * 40}" for c in "bd")
    assert (
        f"The run before judged {first} and gave 1 finding:\n\n"
        "1. **`src/pkg/two.py:1`** Two departs. Fixed.\n\n"
        f"The run before judged {second} and gave 1 finding:\n\n"
        "2. **`CHANGELOG.md:1`** The section is thin. Open: finding 1 above.\n"
    ) in body


# --- the comment ---------------------------------------------------------------------------

MARKER = "<!-- style: reviews/conventions -->"


def comment_of(range_: dict, verdict: str = "ready", findings=(), earlier=None, head="c" * 40):
    result = {"verdict": verdict, "findings": list(findings), "range": range_, "documents": LABELS}
    if earlier is not None:
        result["earlier"] = earlier
    return fr.verdict_comment(result, REPO, head)[0]


def test_the_comment_of_a_range_names_the_run_and_the_commit_it_built_on() -> None:
    built = {"commit": "b" * 40, "ready": True, "run": run_url(5), "by": "range"}
    range_ = {"kind": "range", "commit": "c" * 40, "since": "b" * 40, "tag": "v0.1.0"}
    body = comment_of({**range_, "built": built, "unread": False})
    at = f"https://github.com/{REPO}/commit/{'b' * 40}"
    assert body.startswith(
        f"{MARKER}\n**Approved.** No findings at https://github.com/{REPO}/commit/{'c' * 40}.\n\n"
        f"Judged: the commits from {at} to this commit, before their release, against 2 documents "
        "of `README.md` on `main`.\n\n"
        f"Built on: the run {run_url(5)}, which judged {at} ready. Nothing up to that commit was "
        "judged again.\n\n<!-- conventions-run: "
    )


def test_the_comment_of_a_pull_request_names_its_run_before_and_its_findings() -> None:
    built = {"commit": "b" * 40, "ready": False, "run": None, "by": "pull request"}
    range_ = {"release": True, "since": "b" * 40, "tag": "v0.1.0", "built": built, "unread": False}
    earlier = {"head": "b" * 40, "findings": [{**TWO, "state": "fixed", "finding": None}]}
    body = comment_of(range_, earlier=earlier)
    at = f"https://github.com/{REPO}/commit/{'b' * 40}"
    assert (
        f"Judged: the commits from {at} to the head, against 2 documents of `README.md` on "
        "`main`.\n\n"
        f"Built on: this pull request's run before, which judged {at} not ready. Nothing up to "
        "that commit was judged again.\n\n"
        f"The run before judged {at} and gave 1 finding:\n\n"
        "1. **`src/pkg/two.py:1`** Two departs. Fixed.\n"
    ) in body


@pytest.mark.parametrize(
    ("unread_", "line"),
    [
        (
            False,
            (
                "Built on: nothing. No run before judged a commit of this range, so the whole "
                "range was judged."
            ),
        ),
        (
            True,
            "Built on: nothing. The runs before could not be read, so the whole range was judged.",
        ),
    ],
)
def test_the_comment_of_a_run_that_built_on_none_says_why(unread_: bool, line: str) -> None:
    range_ = {"release": True, "since": "a" * 40, "tag": "v0.1.0", "built": None}
    body = comment_of({**range_, "unread": unread_})
    assert (
        "Judged: the release's range from `v0.1.0` to the head, against 2 documents of "
        f"`README.md` on `main`.\n\n{line}\n\n<!-- conventions-run: "
    ) in body


# --- the dry run ---------------------------------------------------------------------------


def test_a_dry_run_of_a_commit_builds_on_the_judged_commit_and_says_so(
    tmp_path: Path, gh, api, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    source, shas = make_line(tmp_path)

    def clone(repo: str, sha: str, workdir: Path) -> None:
        git(tmp_path, "clone", "-q", str(source), str(workdir))
        git(workdir, "checkout", "-q", "--detach", sha)

    monkeypatch.setattr(fr, "clone_commit", clone)
    bin_dir = gh(answers(judged(shas["m2"], 12, "ready", [])))
    client = api(message([submitted("ready")]))
    assert fr.main(["dry-run", "--repo", REPO, "--commit", shas["m3"]]) == 0
    out = capsys.readouterr().out
    run = f"the run {run_url(5)}"
    assert built_notice(run, shas["m2"], "ready", f"the commit {shas['m3']}") in out
    assert client.messages.requests[0]["messages"][0]["content"].startswith(
        f"Review the range of {REPO} up to the commit {shas['m3']}: this review builds on {run}"
    )
    assert stub_gh.written(bin_dir) == []


def test_a_dry_run_of_a_pull_request_builds_on_the_judged_commit_and_says_so(
    tmp_path: Path, gh, api, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    source, shas = make_release(tmp_path)

    def clone(repo: str, pr: int, sha: str, workdir: Path) -> None:
        git(tmp_path, "clone", "-q", str(source), str(workdir))
        git(workdir, "checkout", "-q", "--detach", sha)

    monkeypatch.setattr(fr, "clone_pull_request", clone)
    view = {
        **pull_request([]),
        "baseRefOid": shas["m3"],
        "headRefOid": shas["head"],
        "labels": [],
    }
    bin_dir = gh(answers(judged(shas["m2"], 12, "not ready", [TWO]), view=view))
    fixed = {"number": 1, "state": "fixed", "finding": None, "reason": ""}
    verdict = submitted("ready")
    verdict["input"]["earlier"] = [fixed]
    client = api(message([verdict]))
    assert fr.main(["dry-run", "--repo", REPO, "--pr", "7"]) == 0
    out = capsys.readouterr().out
    assert built_notice(f"the run {run_url(5)}", shas["m2"], "not ready", "the head") in out
    first = client.messages.requests[0]["messages"][0]["content"]
    assert first.startswith(f"Review the release pull request {REPO}#7: ")
    assert f"This review builds on the run {run_url(5)}, which judged the commit" in first
    assert stub_gh.written(bin_dir) == []


# --- the workflow and the README -----------------------------------------------------------

README_TEXT = (ROOT / "README.md").read_text()


def entry(name: str) -> str:
    text = README_TEXT.split(f"**`.github/workflows/{name}`**", 1)[1]
    return " ".join(text.split("\n- **`.github/workflows/", 1)[0].split())


def test_the_job_range_reads_the_checks_of_its_line() -> None:
    text = (ROOT / ".github" / "workflows" / "conventions-range.yml").read_text()
    job = text.split("\n  range:\n", 1)[1]
    permissions = job.split("    permissions:\n", 1)[1].split("    concurrency:", 1)[0]
    assert permissions.split() == [
        "contents:",
        "read",
        "pull-requests:",
        "write",
        "checks:",
        "read",
    ]


def test_the_readme_says_what_a_review_of_a_pull_request_builds_on() -> None:
    flat = entry("conventions.yml")
    for text in (
        "**What a run builds on**",
        "for the newest commit that a run judged, and judges only what came after it",
        (
            "passed or failed and the comment of that run, whose hidden line names the commit, "
            "stands on the pull request whose merge made it"
        ),
        "the head that its own run before judged counts too where it lies on that line",
        "the newer of the two counts",
        "A skipped check counts for nothing",
        "a check whose comment is missing or names another commit",
        "The run judges the commits after the commit, and the description and the checks as on",
        # Fix round 1 of #142: the states, whatever the run builds on.
        "each finding of that run, ready or not, gets its state",
        "both runs' findings get their states, each finding once",
        "never whether an earlier finding gets its state",
        "a finding that blocked never leaves the comment unsaid",
        "Where no commit of the line was judged, the run judges the whole range as before",
        "A head that does not descend from a judged commit by its first parents",
        "at most 30 seconds a call, 120 seconds together and 100 commits of the line",
        "says in its job summary that it could not read the runs before",
        "`Built on:`",
    ):
        assert text in flat, text
    # The new text cites no record that a reader of this public repository cannot open.
    rule = flat.split("**What a run builds on**", 1)[1].split(" - **", 1)[0]
    for record in ("coordinate-core#", "coordinate-core/issues", "#139", "#100", "#96"):
        assert record not in rule, record


def test_the_readme_says_what_a_run_on_a_range_builds_on() -> None:
    flat = entry("conventions-range.yml")
    for text in (
        "**What a run builds on**",
        "the newest commit of its line after the tag that a run on a range judged",
        "it judges the commits after that commit",
        "it gives each of its findings its state, fixed or open, whatever that run's verdict",
        "a skipped check, a missing comment",
        "count for nothing",
        "builds on none",
        "the job summary and the comment say what the run built on",
    ):
        assert text in flat, text


def test_the_readme_says_the_dry_run_names_what_it_builds_on() -> None:
    section = README_TEXT.split("\n## Running the review locally\n", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(section.split())
    assert "reads the runs before with gh's login and prints which judged commit it builds on" in (
        flat
    )
