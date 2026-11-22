"""The run on a range judges and reports (step 3.1 of .github 0.5.0, .github#129). The job `range`
of conventions-range.yml judges the commits since the last release tag reachable from the commit
of its event, with the judge, the effort, the turn cap and the documents of the review of a release
PR, read as that review reads them. It judges no pull request: its material holds no description
and no checks, and names no release version, and the judge is told so and that the release's own
changes come with the release PR. Without a release tag reachable from the commit the run judges
what the commit changed against its first parent, for a merge the merged pull request's whole
change, as the human decided on .github#138; a commit with no parent is judged on its own change. A
commit that carries the last release tag and a README that links no documents end green with their
notice and no model call. The verdict goes to the job summary and, as the check's comment with its
hidden last line, to one comment on the pull request whose merge made the commit, which a second
run on the same commit rewrites; no comment where no pull request merged the commit, and none on a
release PR. A missing key fails before the caller's commit is checked out. `dry-run --commit`
judges a commit's range as the job does and posts nothing.

The review of a pull request keeps its texts word for word: the instructions, the first messages
and the tools, held by their digests as they stood before this step.

The tests run the script's commands on real temporary git repositories, with a fake Messages
client and a stub `gh` (stub_gh.py); no test needs a key or the network."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import anthropic
import conventions as fr
import pytest
import stub_gh

REPO = "xippios/sdk-usda-psd"
MARKER = "<!-- style: reviews/conventions -->"
EMPTY_KEY = (
    "conventions: ANTHROPIC_API_KEY is empty; the review cannot run. Share the organization "
    "secret with this repository (G4)."
)
OTHER_URL = "https://github.com/xippios/sdk-core/blob/main/docs/conventions.md"
README = (
    "# sdk-usda-psd\n\nA source.\n\n## Documents\n\n"
    "- sdk-usda-psd: [docs/conventions.md](docs/conventions.md) — the conventions.\n"
    f"- sdk-core: [docs/conventions.md]({OTHER_URL}) — the family's.\n"
)
FIRST_FILES = {
    "README.md": README,
    "src/pkg/mod.py": "VALUE = 1\n",
    "docs/conventions.md": "# conventions, main\n",
}
# The last step of the package carries the version the release will ship: the material names
# none all the same.
PYPROJECT = '[project]\nname = "sdk-usda-psd"\nversion = "0.2.0"\n'
LABELS = ["sdk-usda-psd: docs/conventions.md", "sdk-core: docs/conventions.md"]
# The texts of the review of a pull request as they stood before this step, by their digests:
# the instructions, the first message of each kind, the reprompt and the tools.
PULL_REQUEST_TEXTS = {
    "INSTRUCTIONS": "2e3864fa57eaad07d2d3c41bc0ab73277faf023af93225da158ee27faf9c6c0f",
    "FIRST_MESSAGE": "638c83c4687ee9d60c56f5c9895836dd0b4cd3141ee8f18194b01caaa5d193ca",
    "RELEASE_MESSAGE": "c8891680e57375b08676e8d571571bb18e6c8eb2d3651bf286246a241e996d27",
    "UNTAGGED_MESSAGE": "445e8c847bc8b9a748f643fd36aa5b306330b8b2a7332fa5640ef754e757c6ed",
    "EARLIER_MESSAGE": "51b77f5d6ead3b26ef6162497646f1ca2782d2a062c51a8c9e4b831e5f8a3c8b",
    "REPROMPT": "3a3b08dc41ef68f0d74ef1c73c44812b8f9bd8279a2023b213f09c215074cfcd",
}
TOOLS_DIGEST = "a2fac6c1130a61e6883ad18df931a032b248619f59996cba2c04ad1db03cf7c2"
# The texts of the review of a range as step 3.1 left them, which a range that builds on no judged
# commit keeps word for word (step 4 of .github 0.5.0), and the tools of a range.
RANGE_TEXTS = {
    "RANGE_INSTRUCTIONS": "f1bd23217743c0693d53a8a0562ef3a837da258bff693cf360b35058242b7657",
    "RANGE_MESSAGE": "6d4ed76c302fbd06cf9ce9a7f481bf88e30ac5996fdf5d295c5d3c9a66192b4a",
    "UNTAGGED_RANGE_MESSAGE": "c2d9cf7dd74463aadd9c0806d2cf09330adbc2d903db9f7cf82bb3cc2fc99d72",
    "PARENTLESS_RANGE_MESSAGE": "fa4b2a35f41381f4357352eb3ccfe0db7340b068cd87ce4fff50ec138d24297a",
}
RANGE_TOOLS_DIGEST = "2422606b64549bcfe02b5b499d1b8e5e4e00338790cc9020e96499a4d86d8849"
# The texts of a run that builds on a judged commit (step 4 of .github 0.5.0), as fix round 1 of
# #142 settled them: BUILT_INSTRUCTIONS, BUILT_EARLIER_MESSAGE and RANGE_BUILT_INSTRUCTIONS changed.
BUILT_TEXTS = {
    "BUILT_INSTRUCTIONS": "de0280fe73e0172df9dd32c9890253dfa9de9df6bb60eff193b4125d944e5ac4",
    "BUILT_MESSAGE": "ea3abc826cc8d96ad90eb3ea4f9aa4613226361027aee1e628dac4773729def7",
    "BUILT_EARLIER_MESSAGE": "f07b3e555cd84192376acc02788f258dee319756f4c984cf635c2db84b1845ba",
    "RANGE_BUILT_INSTRUCTIONS": "6513a71bc5ef233a4f8c1cd002261cc66d4bcbf9a65348002919d2806395f8a4",
    "RANGE_BUILT_MESSAGE": "3879bea11166716899a4dffb117e41f75c4fdc0b5fd806fbbe415a92cab0fa15",
    "RANGE_BUILT_EARLIER_MESSAGE": (
        "dfde0c07347fbd1358cc3d9cc8d8b821b023366a1ee3e591f127b4166dece32c"
    ),
}
# The read of the checks of a commit of the line, as the run before it asks GitHub (step 4).
CHECK_RUNS = "check-runs?check_name=range%20%2F%20range&per_page=100"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- git ---------------------------------------------------------------------------------


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


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for path, content in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_range(root: Path, *, tag: str | None = "v0.1.0", readme: str = README):
    """A repository whose `main` holds a package's steps since ``tag`` on its first commit: the
    first commit, a step's change, and the last step with the version to ship. Returns the
    checkout, detached at the last commit, and the three commits."""
    ws = root / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    first = commit(ws, {**FIRST_FILES, "README.md": readme}, "feat: the first commit")
    if tag:
        git(ws, "tag", tag)
    second = commit(ws, {"src/pkg/mod.py": "VALUE = 2\n"}, "feat: a step's change\n\nWith a body.")
    third = commit(ws, {"pyproject.toml": PYPROJECT, "src/pkg/new.py": "NEW = 1\n"}, "feat: last")
    git(ws, "checkout", "-q", "--detach", third)
    return ws, first, second, third


@pytest.fixture
def gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The stub `gh` first on the path, answering a document of another repository."""
    bin_dir = stub_gh.install(tmp_path / "bin", {"document": "# conventions of sdk-core\n"})
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


@pytest.fixture
def actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """The step summary and the step outputs, as Actions sets them."""
    files = {"summary": tmp_path / "summary.md", "output": tmp_path / "output.txt"}
    for path in files.values():
        path.write_text("")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(files["summary"]))
    monkeypatch.setenv("GITHUB_OUTPUT", str(files["output"]))
    return files


def range_prepare(ws: Path, sha: str) -> int:
    return fr.main(
        ["range-prepare", "--repo", REPO, "--commit", sha, "--workspace", str(ws), "--main", "main"]
    )


# --- the material of a range -------------------------------------------------------------


def test_the_review_of_a_pull_request_keeps_its_texts_word_for_word() -> None:
    """The instructions, the first messages, the reprompt and the tools of the review of a pull
    request are what they were before the range got its own (.github#129)."""
    for name, expected in PULL_REQUEST_TEXTS.items():
        assert digest(getattr(fr, name)) == expected, name
    assert digest(json.dumps(fr.TOOLS, sort_keys=True)) == TOOLS_DIGEST


def test_a_run_that_builds_on_nothing_keeps_its_texts_and_the_new_ones_are_held() -> None:
    """The texts of a range as step 3.1 left them stay word for word, and the texts of a run that
    builds on a judged commit are held as step 4 of .github 0.5.0 settled them."""
    for name, expected in {**RANGE_TEXTS, **BUILT_TEXTS}.items():
        assert digest(getattr(fr, name)) == expected, name
    assert digest(json.dumps(fr.RANGE_TOOLS, sort_keys=True)) == RANGE_TOOLS_DIGEST


def test_prepare_writes_the_material_of_a_range_without_a_pull_request(
    tmp_path: Path, gh: Path, actions: dict[str, Path], capsys
) -> None:
    ws, first, second, third = make_range(tmp_path)
    (ws / ".review").mkdir()
    (ws / ".review" / "planted.txt").write_text("from the range\n")

    assert range_prepare(ws, third) == 0
    review = ws / ".review"
    # No description and no checks: the range judges no pull request.
    assert sorted(p.name for p in review.iterdir()) == [
        "diff.patch",
        "documents",
        "documents.json",
        "log.txt",
        "meta.json",
    ]
    # The tag and the commit, and no version, though the commit's pyproject.toml names one.
    meta = json.loads((review / "meta.json").read_text())
    assert meta == {
        "kind": "range",
        "repo": REPO,
        "commit": third,
        "main": "main",
        "since": first,
        "tag": "v0.1.0",
        "built": None,
        "unread": None,
    }
    diff = (review / "diff.patch").read_text()
    assert "-VALUE = 1\n+VALUE = 2" in diff
    assert "+NEW = 1" in diff
    assert "version = " in diff
    assert "README.md" not in diff
    log = (review / "log.txt").read_text()
    assert log.startswith(f"commit {third}\n")
    assert f"commit {second}\n" in log
    assert "\n\nfeat: a step's change\n\nWith a body.\n" in log
    assert first not in log
    # Nothing is asked of a pull request: the checks of the one commit of the line between the
    # tag and the commit are read (step 4 of .github 0.5.0), then the other repository's document.
    assert stub_gh.calls(gh) == [
        ["api", f"repos/{REPO}/commits/{second}/{CHECK_RUNS}"],
        [
            "api",
            "repos/xippios/sdk-core/contents/docs/conventions.md?ref=main",
            "-H",
            "Accept: application/vnd.github.raw+json",
        ],
    ]
    documents = json.loads((review / "documents.json").read_text())
    assert [entry["label"] for entry in documents] == LABELS
    notice = f"conventions: the review judges the range from v0.1.0 to the commit {third}"
    summary = actions["summary"].read_text().splitlines()
    assert summary[0] == notice
    assert summary[-2] == "conventions: 2 documents of README.md on main"
    assert summary[-1] == fr.NONE_JUDGED
    assert "version" not in actions["summary"].read_text()
    assert actions["output"].read_text() == "review=true\n"
    assert notice in capsys.readouterr().out


def untagged_notice(sha: str, parent: str | None) -> str:
    """The sentence of a commit with no release tag reachable (the answer of .github#138)."""
    head = "conventions: no release tag is reachable from the commit; the review judges what "
    if parent is None:
        return f"{head}{sha} changed, since it has no parent"
    return f"{head}{sha} changed against its first parent {parent}"


def make_merge(root: Path) -> tuple[Path, dict[str, str]]:
    """A repository with no release tag whose `main` merged a step's branch of two commits by a
    merge commit, after a commit of its own: the history before the merge holds the first
    commit, an earlier step and that commit. Returns the checkout, detached at the merge, and
    the commits by name."""
    ws = root / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    shas = {"first": commit(ws, FIRST_FILES, "feat: the first commit")}
    shas["before"] = commit(ws, {"src/pkg/mod.py": "VALUE = 2\n"}, "feat: an earlier step")
    git(ws, "checkout", "-q", "-b", "step")
    shas["one"] = commit(ws, {"src/pkg/new.py": "NEW = 1\n"}, "feat: the step's first commit")
    shas["two"] = commit(
        ws, {"src/pkg/new.py": "NEW = 2\n", "pyproject.toml": PYPROJECT}, "feat: its second"
    )
    git(ws, "checkout", "-q", "main")
    shas["other"] = commit(ws, {"src/pkg/other.py": "OTHER = 1\n"}, "feat: a merge before it")
    git(ws, "merge", "-q", "--no-ff", "-m", "Merge pull request #7 from xippios/step", "step")
    shas["merge"] = git(ws, "rev-parse", "HEAD")
    git(ws, "checkout", "-q", "--detach", shas["merge"])
    return ws, shas


def test_a_merge_without_a_release_tag_is_judged_against_its_first_parent(
    tmp_path: Path, gh: Path, actions: dict[str, Path]
) -> None:
    """The range is the merged pull request's whole change: every commit of the merged branch,
    and none of the history before the merge (the answer of .github#138)."""
    ws, shas = make_merge(tmp_path)
    assert range_prepare(ws, shas["merge"]) == 0
    review = ws / ".review"
    meta = json.loads((review / "meta.json").read_text())
    assert (meta["since"], meta["tag"]) == (shas["other"], None)
    assert set(meta) == {"kind", "repo", "commit", "main", "since", "tag", "built", "unread"}
    assert (meta["built"], meta["unread"]) == (None, None)
    diff = (review / "diff.patch").read_text()
    assert "+NEW = 2" in diff
    assert "version = " in diff
    for absent in ("OTHER", "VALUE", "README.md", "docs/conventions.md"):
        assert absent not in diff, absent
    log = (review / "log.txt").read_text()
    for name in ("merge", "two", "one"):
        assert f"commit {shas[name]}\n" in log, name
    for name in ("first", "before", "other"):
        assert shas[name] not in log, name
    summary = actions["summary"].read_text().splitlines()
    assert summary[0] == untagged_notice(shas["merge"], shas["other"])
    assert actions["output"].read_text() == "review=true\n"


def test_a_plain_commit_without_a_release_tag_is_judged_on_its_own_change(
    tmp_path: Path, gh: Path, actions: dict[str, Path]
) -> None:
    ws, first, second, third = make_range(tmp_path, tag=None)
    # A tag on another branch and a tag of another form are no release tag of the commit.
    git(ws, "checkout", "-q", "-b", "side", first)
    commit(ws, {"side.txt": "side\n"}, "feat: a side branch")
    git(ws, "tag", "v9.9.9")
    git(ws, "tag", "release-1", first)
    git(ws, "checkout", "-q", "--detach", third)

    assert range_prepare(ws, third) == 0
    review = ws / ".review"
    meta = json.loads((review / "meta.json").read_text())
    assert (meta["since"], meta["tag"]) == (second, None)
    diff = (review / "diff.patch").read_text()
    assert "+NEW = 1" in diff
    for absent in ("VALUE", "+# sdk-usda-psd", "side.txt"):
        assert absent not in diff, absent
    log = (review / "log.txt").read_text()
    assert log.startswith(f"commit {third}\n")
    assert first not in log
    assert second not in log
    assert actions["summary"].read_text().splitlines()[0] == untagged_notice(third, second)
    assert actions["output"].read_text() == "review=true\n"


def test_the_first_commit_without_a_release_tag_is_judged_on_its_own_change(
    tmp_path: Path, gh: Path, actions: dict[str, Path]
) -> None:
    """A commit with no parent: its change is the whole tree it adds, from the empty tree."""
    ws = tmp_path / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    first = commit(ws, FIRST_FILES, "feat: the first commit")
    assert range_prepare(ws, first) == 0
    review = ws / ".review"
    meta = json.loads((review / "meta.json").read_text())
    assert (meta["since"], meta["tag"]) == (None, None)
    assert "+# sdk-usda-psd" in (review / "diff.patch").read_text()
    assert (review / "log.txt").read_text().startswith(f"commit {first}\n")
    assert actions["summary"].read_text().splitlines()[0] == untagged_notice(first, None)
    assert actions["output"].read_text() == "review=true\n"


def test_a_readme_without_documents_ends_green_with_its_notice(
    tmp_path: Path, gh: Path, actions: dict[str, Path]
) -> None:
    ws, _first, _second, third = make_range(tmp_path, readme="# sdk-usda-psd\n\nNo documents.\n")
    assert range_prepare(ws, third) == 0
    notice = (
        "conventions: README.md on main links no documents under ## Documents; nothing to judge"
    )
    assert notice in actions["summary"].read_text().splitlines()
    assert actions["output"].read_text() == "review=false\n"
    assert stub_gh.calls(gh) == []


def empty_notice(sha: str, tag: str) -> str:
    """The sentence of a commit that carries the last release tag (finding 2 of the review of
    .github#137)."""
    return (
        f"conventions: the commit {sha} carries the last release tag {tag}; no commit came after "
        "it, so the range holds nothing to judge"
    )


def test_a_commit_that_carries_the_last_release_tag_ends_green_with_nothing_to_judge(
    tmp_path: Path, gh: Path, actions: dict[str, Path], capsys
) -> None:
    """The range is empty: no material for the judge, `review=false`, so the job makes no model
    call, posts no comment and passes with its sentence in the job summary."""
    ws, _first, _second, third = make_range(tmp_path)
    git(ws, "tag", "v0.2.0", third)
    assert range_prepare(ws, third) == 0
    notice = empty_notice(third, "v0.2.0")
    assert actions["summary"].read_text().splitlines() == [notice]
    assert notice in capsys.readouterr().out
    assert actions["output"].read_text() == "review=false\n"
    assert stub_gh.calls(gh) == []
    assert sorted(p.name for p in (ws / ".review").iterdir()) == []


def test_a_commit_one_after_the_release_tag_is_still_judged(
    tmp_path: Path, gh: Path, actions: dict[str, Path]
) -> None:
    ws, _first, second, third = make_range(tmp_path)
    git(ws, "tag", "v0.2.0", second)
    assert range_prepare(ws, third) == 0
    meta = json.loads((ws / ".review" / "meta.json").read_text())
    assert (meta["since"], meta["tag"]) == (second, "v0.2.0")
    log = (ws / ".review" / "log.txt").read_text()
    assert log.startswith(f"commit {third}\n")
    assert second not in log
    assert "+NEW = 1" in (ws / ".review" / "diff.patch").read_text()
    assert actions["output"].read_text() == "review=true\n"


@pytest.mark.parametrize("sha", ["c" * 7, "main", ""])
def test_range_prepare_takes_a_full_commit_alone(
    tmp_path: Path, gh: Path, actions: dict[str, Path], sha: str, capsys
) -> None:
    ws, _first, _second, _third = make_range(tmp_path)
    assert range_prepare(ws, sha) == 2
    assert "conventions: --commit must be a full commit SHA" in capsys.readouterr().out
    assert not (ws / ".review").exists()


# --- the judge's texts -------------------------------------------------------------------


def prepared(tmp_path: Path, gh: Path, *, tag: str | None = "v0.1.0") -> tuple[fr.Material, str]:
    """The material of the last commit of `make_range`, and where its range starts: the tag's
    commit, or without a tag its first parent."""
    ws, first, second, third = make_range(tmp_path, tag=tag)
    assert range_prepare(ws, third) == 0
    return fr.load_material(ws, ws / ".review"), first if tag else second


def test_a_range_has_instructions_of_its_own(tmp_path: Path, gh: Path, actions) -> None:
    material, _first = prepared(tmp_path, gh)
    assert material.is_range
    system = fr.system_prompt(material, fr.MAX_TURNS)
    text = system[0]["text"]
    assert text == fr.RANGE_INSTRUCTIONS.format(review=".review", max_turns=fr.MAX_TURNS)
    assert text != fr.INSTRUCTIONS.format(review=".review", max_turns=fr.MAX_TURNS)
    flat = " ".join(text.split())
    for said in (
        (
            "You judge no pull request: there is no title, no description, no comment and no "
            "check result, and their absence is no finding."
        ),
        (
            "the release's own changes, the version's bump, the changelog's section of the "
            "version and the tag, come with the release pull request after it, so their absence "
            "is no finding either"
        ),
        "its file (empty when it concerns the range as a whole)",
        "at most 160 turns",
        # The answer of .github#138.
        (
            "or, where no release tag is reachable, what that commit changed against its first "
            "parent, which for a merge is the merged pull request's whole change"
        ),
    ):
        assert said in flat, said
    for absent in ("pr.json", "checks.json", "earlier.json", "the opener", "every commit"):
        assert absent not in text, absent
    assert "first commit" not in flat
    # The documents follow as for a pull request, cached; nothing names the commit.
    assert [block["text"].split("\n", 1)[0] for block in system[1:]] == [
        f"The document `{LABELS[0]}`, read from main:",
        f"The document `{LABELS[1]}`, read from {OTHER_URL}:",
    ]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}
    for block in system:
        assert material.head not in block["text"]


def test_the_first_message_names_the_commit_the_tag_and_no_version(
    tmp_path: Path, gh: Path, actions
) -> None:
    material, first = prepared(tmp_path, gh)
    text = fr.first_message(material)["content"]
    assert text == (
        f"Review the range of {REPO} up to the commit {material.head}: the commits from the "
        f"release tag v0.1.0 ({first}), the last one reachable from that commit, to the commit. "
        "It is no pull request, and the release that follows it is not in it yet. Its material "
        "is under `.review/`, the 2 documents under `.review/documents/`. Read what you need "
        "with the tools, then call `submit_verdict`."
    )
    assert "version" not in text
    assert "#" not in text


def test_the_first_message_of_a_range_without_a_tag_names_the_first_parent(
    tmp_path: Path, gh: Path, actions
) -> None:
    material, parent = prepared(tmp_path, gh, tag=None)
    text = fr.first_message(material)["content"]
    assert text == (
        f"Review the range of {REPO} up to the commit {material.head}: no release tag is "
        f"reachable from it, so the range is what it changed against its first parent {parent}, "
        "for a merge the merged pull request's whole change. It is no pull request, and the "
        "release that follows it is not in it yet. Its material is under `.review/`, the 2 "
        "documents under `.review/documents/`. Read what you need with the tools, then call "
        "`submit_verdict`."
    )
    for absent in ("first commit", "every commit", "version"):
        assert absent not in text, absent


def test_the_first_message_of_a_commit_with_no_parent_names_its_own_change(
    tmp_path: Path, gh: Path, actions
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    first = commit(ws, FIRST_FILES, "feat: the first commit")
    assert range_prepare(ws, first) == 0
    text = fr.first_message(fr.load_material(ws, ws / ".review"))["content"]
    assert text.startswith(
        f"Review the range of {REPO} up to the commit {first}: no release tag is reachable from "
        "it, and it has no parent, so the range is its own change. It is no pull request, and "
        "the release that follows it is not in it yet. Its material is under `.review/`"
    )
    for absent in ("first commit", "every commit"):
        assert absent not in text, absent


def test_the_tools_of_a_range_say_the_range_where_a_pull_requests_say_the_pull_request() -> None:
    assert [tool["name"] for tool in fr.RANGE_TOOLS] == [tool["name"] for tool in fr.TOOLS]
    assert fr.RANGE_TOOLS[:3] == fr.TOOLS[:3]
    schema = fr.RANGE_TOOLS[3]["input_schema"]
    item = schema["properties"]["findings"]["items"]["properties"]
    assert item["file"]["description"] == (
        "The file, empty when the finding concerns the range as a whole."
    )
    pull = fr.TOOLS[3]["input_schema"]["properties"]["findings"]["items"]["properties"]
    assert pull["file"]["description"] == (
        "The file, empty when the finding concerns the pull request as a whole."
    )
    assert {**item, "file": pull["file"]} == pull


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "range", "commit": "c" * 7},
        {"repo": "not a repository"},
        {"since": None},
        {"since": "not a commit"},
        {"tag": 7},
    ],
)
def test_a_range_meta_that_does_not_read_is_no_verdict(
    tmp_path: Path, gh: Path, actions, monkeypatch: pytest.MonkeyPatch, change: dict
) -> None:
    ws, _first, _second, third = make_range(tmp_path)
    assert range_prepare(ws, third) == 0
    meta_file = ws / ".review" / "meta.json"
    meta_file.write_text(json.dumps({**json.loads(meta_file.read_text()), **change}))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-tests")
    monkeypatch.setattr(fr, "make_client", lambda *key: pytest.fail("no client"))
    outcome = fr.review(ws, ws / ".review")
    assert outcome.verdict is None
    assert outcome.reason.startswith(".review/meta.json names no ")


# --- the review of a range ---------------------------------------------------------------


def message(content: list, stop_reason: str = "tool_use"):
    data = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": fr.MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "stop_details": None,
        "usage": {"input_tokens": 10, "output_tokens": 1},
    }
    return anthropic.types.Message.model_validate(data)


def submitted(value: str = "ready", findings: tuple = ()) -> dict:
    return {
        "type": "tool_use",
        "id": "toolu_v",
        "name": "submit_verdict",
        "input": {"verdict": value, "findings": list(findings)},
    }


def finding(file="src/pkg/new.py", line=1, blocking=False, text="A finding.", document=""):
    return {"document": document, "file": file, "line": line, "blocking": blocking, "text": text}


class FakeStream:
    def __init__(self, item) -> None:
        self.item = item

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def get_final_message(self):
        return self.item


class FakeMessages:
    def __init__(self, script) -> None:
        self.script = list(script)
        self.requests = []

    def stream(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return FakeStream(self.script.pop(0))


class FakeClient:
    def __init__(self, script) -> None:
        self.messages = FakeMessages(script)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-tests")

    def install(*script):
        client = FakeClient(script)
        monkeypatch.setattr(fr, "make_client", lambda *key: client)
        return client

    return install


def test_the_review_of_a_range_runs_the_judge_of_a_release_pr_on_its_material(
    tmp_path: Path, gh: Path, actions, api
) -> None:
    ws, first, _second, third = make_range(tmp_path)
    assert range_prepare(ws, third) == 0
    client = api(message([submitted("ready", [finding(file="", line=None)])]))
    out = tmp_path / "verdict.json"
    code = fr.main(
        ["review", "--workspace", str(ws), "--review", str(ws / ".review"), "--out", str(out)]
    )
    assert code == 0
    request = client.messages.requests[0]
    assert (request["model"], request["output_config"]) == (fr.MODEL, {"effort": fr.EFFORT})
    assert request["tools"] == fr.RANGE_TOOLS
    assert request["messages"][0]["content"].startswith(f"Review the range of {REPO} up to ")
    result = json.loads(out.read_text())
    assert result["range"] == {
        "kind": "range",
        "commit": third,
        "since": first,
        "tag": "v0.1.0",
        "built": None,
        "unread": False,
    }
    assert (result["repo"], result["pr"], result["head"]) == (REPO, None, third)
    assert result["documents"] == LABELS
    assert result["summary"].startswith("conventions: verdict=ready findings=1 blocking=0 ")


# --- the key -----------------------------------------------------------------------------


@pytest.mark.parametrize(("has_key", "code"), [("true", 0), ("false", 1), ("", 1)])
def test_the_key_step_fails_with_the_sentence_of_the_review_of_a_pull_request(
    actions: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys, has_key: str, code: int
) -> None:
    monkeypatch.setenv("HAS_KEY", has_key)
    assert fr.main(["range-key"]) == code
    said = [EMPTY_KEY] if code else []
    assert actions["summary"].read_text().splitlines() == said
    assert capsys.readouterr().out.splitlines() == said
    assert actions["output"].read_text() == ""


def test_the_key_sentence_is_the_gates(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """The Gate of a pull request says the same sentence where the secret is empty."""
    for name, value in {"HAS_KEY": "false", "MODE": "all", "REPO": REPO}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HEAD_REPO", REPO)
    assert fr.main(["gate"]) == 1
    assert capsys.readouterr().out.splitlines() == [EMPTY_KEY]


# --- the verdict -------------------------------------------------------------------------

COMMIT = "c" * 40
COMMIT_URL = f"https://github.com/{REPO}/commit/{COMMIT}"
COMMENTS = f"repos/{REPO}/issues/7/comments"
# The pull request whose merge made the commit: a package's last step, no release PR.
STEP_PR = {"title": "0.5.0 Step 4: The last step", "labels": []}


def result(
    verdict: str | None,
    findings: list[dict],
    *,
    tag: str | None = "v0.1.0",
    since: str | None = "a" * 40,
) -> dict:
    """A range's verdict file: ``since`` is the tag's commit, or without a tag the first parent,
    None for a commit with no parent."""
    return {
        "verdict": verdict,
        "findings": findings,
        "reason": None if verdict else "API error: APIConnectionError: Connection error.",
        "range": {"kind": "range", "commit": COMMIT, "since": since, "tag": tag},
        "documents": LABELS,
        "repo": REPO,
        "pr": None,
        "head": COMMIT,
        "summary": f"conventions: verdict={verdict} …" if verdict else "conventions: no verdict …",
        "cost_estimate_usd": 1.2345,
        "cost_estimate_basis": "estimate",
    }


def run_line(findings: list[dict], head: str = COMMIT) -> str:
    run = {"head": head, "findings": [{key: f[key] for key in fr.FINDING_KEYS} for f in findings]}
    blob = json.dumps(run, ensure_ascii=True, separators=(",", ":"))
    return "<!-- conventions-run: " + blob.replace("<", "\\u003c").replace(">", "\\u003e") + " -->"


def range_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: dict | None,
    *,
    pr: str = "7",
    view: dict = STEP_PR,
    comments: tuple = ([],),
    fails: tuple[str, ...] = (),
) -> tuple[int, str, list[list[str]], list[dict]]:
    """Run `range-verdict` on the verdict file ``data``: its exit code, the job summary, the
    calls of `gh` and its writes. ``view`` is the pull request's title and labels, ``comments``
    the pages of its comments; ``fails`` names the reads that fail, `view` or `comments`, and
    `write` for every write."""
    answers = {
        "view": None if "view" in fails else view,
        "comments": None if "comments" in fails else list(comments),
        "write_fails": "write" in fails,
    }
    bin_dir = stub_gh.install(tmp_path / "bin", answers)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    summary = tmp_path / "summary.md"
    summary.write_text("")
    result_file = tmp_path / "verdict.json"
    result_file.unlink(missing_ok=True)
    if data is not None:
        result_file.write_text(json.dumps(data))
    for name, value in {
        "GITHUB_STEP_SUMMARY": str(summary),
        "RESULT_FILE": str(result_file),
        "GH_TOKEN": "dummy",
        "REPO": REPO,
        "PR": pr,
        "COMMIT": COMMIT,
    }.items():
        monkeypatch.setenv(name, value)
    code = fr.main(["range-verdict"])
    return code, summary.read_text(), stub_gh.calls(bin_dir), stub_gh.written(bin_dir)


def test_the_verdict_goes_to_the_summary_and_to_one_comment_on_the_merged_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = [
        finding(document="sdk-core: docs/conventions.md#tests", text="No test for it."),
        finding(file="", line=None, text="The range leaves the table stale."),
    ]
    code, summary, calls, writes = range_verdict(tmp_path, monkeypatch, result("ready", findings))
    assert code == 0
    body = (
        f"{MARKER}\n"
        f"**Findings.** 2 findings, none blocking, at {COMMIT_URL}.\n\n"
        "Judged: the commits from `v0.1.0` to this commit, before their release, against 2 "
        "documents of `README.md` on `main`.\n\n"
        "1. **sdk-core: docs/conventions.md#tests** No test for it. `src/pkg/new.py:1`. "
        "Blocks: no.\n"
        "2. **the range** The range leaves the table stale. Blocks: no.\n\n"
        f"{run_line(findings)}\n"
    )
    assert summary == body
    assert calls == [
        ["pr", "view", "7", "--json", "title,labels", "--repo", REPO],
        ["api", f"{COMMENTS}?per_page=100&page=1"],
        ["api", "--method", "POST", COMMENTS, "--input", "-"],
    ]
    assert writes == [{"method": "POST", "endpoint": COMMENTS, "input": {"body": body}}]


@pytest.mark.parametrize(
    ("since", "judged"),
    [
        (
            "a" * 40,
            (
                "what this commit changed against its first parent, since no release tag is "
                "reachable from it"
            ),
        ),
        (
            None,
            (
                "what this commit changed, since no release tag is reachable from it and it has "
                "no parent"
            ),
        ),
    ],
)
def test_a_blocking_finding_fails_the_check_and_posts_the_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, since: str | None, judged: str
) -> None:
    """Without a release tag the comment says what was judged in its place (.github#138)."""
    findings = [finding(blocking=True, text="The rule is broken.")]
    code, summary, _calls, writes = range_verdict(
        tmp_path, monkeypatch, result("ready", findings, tag=None, since=since)
    )
    assert code == 1
    assert summary.startswith(
        f"{MARKER}\n**Blocked.** 1 finding, 1 blocking, at {COMMIT_URL}.\n\n"
        f"Judged: {judged}, against 2 documents of `README.md` on `main`.\n"
    )
    assert "every commit" not in summary
    assert writes[0]["input"]["body"] == summary


def test_a_second_run_on_the_same_commit_rewrites_its_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run's comment is the check's whose hidden line names the judged commit; the comment
    of the pull request's own review, which names its head, and another workflow's stay."""
    own_review = f"{MARKER}\n**Approved.** No findings.\n\n{run_line([], head='e' * 40)}\n"
    earlier = f"{MARKER}\n**Blocked.** 1 finding.\n\n{run_line([finding(blocking=True)])}\n"
    pages = [
        [stub_gh.comment(number, "Other text.", "someone") for number in range(1, 100)]
        + [stub_gh.comment(100, own_review)],
        [
            stub_gh.comment(101, earlier),
            stub_gh.comment(102, f"{MARKER}\nCopied by hand.\n\n{run_line([])}\n", "someone"),
            stub_gh.comment(103, "<!-- another workflow -->\nIts own."),
            # An item of another shape is no comment of the run's, and reading goes on.
            "not a comment",
            {"id": True, "user": {"login": "github-actions[bot]"}, "body": earlier},
        ],
    ]
    code, summary, calls, writes = range_verdict(
        tmp_path, monkeypatch, result("ready", []), comments=pages
    )
    assert code == 0
    assert summary.startswith(f"{MARKER}\n**Approved.** No findings at {COMMIT_URL}.\n")
    assert calls[1:] == [
        ["api", f"{COMMENTS}?per_page=100&page=1"],
        ["api", f"{COMMENTS}?per_page=100&page=2"],
        ["api", "--method", "PATCH", f"repos/{REPO}/issues/comments/101", "--input", "-"],
    ]
    assert writes == [
        {
            "method": "PATCH",
            "endpoint": f"repos/{REPO}/issues/comments/101",
            "input": {"body": summary},
        }
    ]


def test_the_comment_of_the_pull_requests_own_review_is_never_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    own_review = f"{MARKER}\n**Approved.** No findings.\n\n{run_line([], head='e' * 40)}\n"
    _code, _summary, _calls, writes = range_verdict(
        tmp_path, monkeypatch, result("ready", []), comments=[[stub_gh.comment(9, own_review)]]
    )
    assert [write["method"] for write in writes] == ["POST"]


def test_comments_that_cannot_be_read_get_a_new_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As on a pull request: a new comment is posted, and none is overwritten unread."""
    code, _summary, calls, writes = range_verdict(
        tmp_path, monkeypatch, result("ready", []), fails=("comments",)
    )
    assert code == 0
    assert calls[1] == ["api", f"{COMMENTS}?per_page=100&page=1"]
    assert [write["method"] for write in writes] == ["POST"]


def test_without_a_pull_request_the_summary_alone_carries_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dispatch on a commit that no merge made: the gate's `pr` is empty."""
    code, summary, calls, writes = range_verdict(tmp_path, monkeypatch, result("ready", []), pr="")
    assert code == 0
    assert calls == writes == []
    assert summary.startswith(f"{MARKER}\n**Approved.** No findings at {COMMIT_URL}.\n")
    assert summary.endswith(
        "\nconventions: no pull request's merge made the commit; the job summary alone carries "
        "the verdict\n"
    )


@pytest.mark.parametrize(
    "view",
    [
        {"title": "0.7.4 Release", "labels": []},
        {"title": "Ship the next version", "labels": [{"name": "Release"}]},
    ],
)
def test_a_release_pr_on_a_dispatch_gets_no_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view: dict
) -> None:
    code, summary, calls, writes = range_verdict(
        tmp_path, monkeypatch, result("not ready", [finding(blocking=True)]), view=view
    )
    assert code == 1
    assert calls == [["pr", "view", "7", "--json", "title,labels", "--repo", REPO]]
    assert writes == []
    assert summary.endswith(
        "\nconventions: #7 is a release PR, which carries the comment of its own review; the job "
        "summary alone carries the verdict\n"
    )


def test_a_pull_request_that_cannot_be_read_gets_no_comment_and_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    code, summary, calls, writes = range_verdict(
        tmp_path, monkeypatch, result("ready", []), fails=("view",)
    )
    assert code == 0
    assert len(calls) == 1
    assert writes == []
    line = (
        "conventions: reading #7 failed: gh: Server Error (HTTP 502); no comment is posted, and "
        "the job summary alone carries the verdict"
    )
    assert summary.endswith(f"\n{line}\n")
    assert f"::warning::{line}" in capsys.readouterr().out


def test_a_failed_post_is_in_the_summary_and_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    code, summary, _calls, writes = range_verdict(
        tmp_path, monkeypatch, result("ready", []), fails=("write",)
    )
    assert code == 0
    assert len(writes) == 1
    line = (
        "conventions: posting the PR comment failed: HTTP 403: Resource not accessible by "
        "integration ([redacted])"
    )
    assert summary.endswith(f"\n{line}\n")
    assert f"::warning::{line}" in capsys.readouterr().out


@pytest.mark.parametrize("data", [None, "no verdict"])
def test_no_verdict_fails_with_the_scripts_line_and_posts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data
) -> None:
    given = None if data is None else result(None, [])
    code, summary, calls, writes = range_verdict(tmp_path, monkeypatch, given)
    assert code == 1
    assert calls == writes == []
    assert summary.startswith("## conventions: no verdict\n\n")
    assert summary.endswith("\n\nThe review returned no verdict; the check fails.\n")


def test_the_summary_and_the_comment_carry_no_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _code, summary, _calls, writes = range_verdict(tmp_path, monkeypatch, result("ready", []))
    for text in (summary, writes[0]["input"]["body"]):
        assert "1.2345" not in text
        assert "estimate" not in text


# --- the dry run of a commit -------------------------------------------------------------


@pytest.fixture
def cloned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`clone_commit` from the local source: the clone's `origin/main` is the source's main."""
    source, first, _second, third = make_range(tmp_path)
    clones = []

    def clone(repo: str, sha: str, workdir: Path) -> None:
        clones.append((repo, sha))
        git(tmp_path, "clone", "-q", str(source), str(workdir))
        git(workdir, "checkout", "-q", "--detach", sha)

    monkeypatch.setattr(fr, "clone_commit", clone)
    monkeypatch.setattr(
        fr, "clone_pull_request", lambda *a: pytest.fail("a commit's dry run clones no PR")
    )
    return first, third, clones


def test_a_dry_run_of_a_commit_judges_its_range_and_posts_nothing(
    tmp_path: Path, gh: Path, api, cloned, capsys
) -> None:
    first, third, clones = cloned
    client = api(message([submitted("not ready", [finding(file="", line=None, blocking=True)])]))
    out = tmp_path / "dry.json"
    code = fr.main(["dry-run", "--repo", REPO, "--commit", third, "--out", str(out)])
    assert code == 1
    assert clones == [(REPO, third)]
    first_message = client.messages.requests[0]["messages"][0]["content"]
    assert first_message.startswith(f"Review the range of {REPO} up to the commit {third}: ")
    assert f"release tag v0.1.0 ({first})" in first_message
    assert client.messages.requests[0]["tools"] == fr.RANGE_TOOLS
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2].startswith("conventions: verdict=not ready findings=1 blocking=1 ")
    assert lines[-1] == "the range [blocking] A finding."
    assert json.loads(out.read_text())["range"]["kind"] == "range"
    # It reads the checks of the line (step 4 of .github 0.5.0) and the other repository's
    # document, and asks nothing of a pull request.
    # The one commit of the line between the tag's commit and the commit is read.
    calls = stub_gh.calls(gh)
    checked = [call[1] for call in calls if call[1].endswith(f"/{CHECK_RUNS}")]
    assert len(checked) == 1
    assert first not in checked[0]
    assert third not in checked[0]
    assert all(call[0] == "api" and "/contents/" in call[1] for call in calls[1:])
    assert stub_gh.written(gh) == []


def test_a_dry_run_of_a_commit_whose_readme_links_no_documents_ends_green(
    tmp_path: Path, gh: Path, api, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _first, _second, third = make_range(tmp_path, readme="# sdk-usda-psd\n")

    def clone(repo: str, sha: str, workdir: Path) -> None:
        git(tmp_path, "clone", "-q", str(source), str(workdir))
        git(workdir, "checkout", "-q", "--detach", sha)

    monkeypatch.setattr(fr, "clone_commit", clone)
    api()
    assert fr.main(["dry-run", "--repo", REPO, "--commit", third]) == 0


def test_a_dry_run_of_a_merge_without_a_release_tag_judges_it_against_its_first_parent(
    tmp_path: Path, gh: Path, api, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The dry run of a commit follows the answer of .github#138 as the job does."""
    source, shas = make_merge(tmp_path)

    def clone(repo: str, sha: str, workdir: Path) -> None:
        git(tmp_path, "clone", "-q", str(source), str(workdir))
        git(workdir, "checkout", "-q", "--detach", sha)

    monkeypatch.setattr(fr, "clone_commit", clone)
    client = api(message([submitted("ready")]))
    out = tmp_path / "dry.json"
    code = fr.main(["dry-run", "--repo", REPO, "--commit", shas["merge"], "--out", str(out)])
    assert code == 0
    first_message = client.messages.requests[0]["messages"][0]["content"]
    assert first_message.startswith(
        f"Review the range of {REPO} up to the commit {shas['merge']}: no release tag is "
        f"reachable from it, so the range is what it changed against its first parent "
        f"{shas['other']}, for a merge the merged pull request's whole change."
    )
    assert untagged_notice(shas["merge"], shas["other"]) in capsys.readouterr().out
    assert json.loads(out.read_text())["range"] == {
        "kind": "range",
        "commit": shas["merge"],
        "since": shas["other"],
        "tag": None,
        "built": None,
        "unread": False,
    }


def test_a_dry_run_of_a_commit_that_carries_the_last_release_tag_makes_no_model_call(
    tmp_path: Path, gh: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    source, _first, _second, third = make_range(tmp_path)
    git(source, "tag", "v0.2.0", third)

    def clone(repo: str, sha: str, workdir: Path) -> None:
        git(tmp_path, "clone", "-q", str(source), str(workdir))
        git(workdir, "checkout", "-q", "--detach", sha)

    monkeypatch.setattr(fr, "clone_commit", clone)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-tests")
    monkeypatch.setattr(fr, "make_client", lambda *key: pytest.fail("no model call"))
    assert fr.main(["dry-run", "--repo", REPO, "--commit", third]) == 0
    assert empty_notice(third, "v0.2.0") in capsys.readouterr().out
    assert stub_gh.calls(gh) == []


@pytest.mark.parametrize(
    "extra",
    [
        ["--commit", "c" * 7],
        ["--commit", "main"],
    ],
)
def test_a_dry_run_takes_a_full_commit_before_any_clone(
    api, cloned, capsys, extra: list[str]
) -> None:
    api()
    _first, _third, clones = cloned
    assert fr.main(["dry-run", "--repo", REPO, *extra]) == 2
    assert clones == []
    assert "conventions: --commit must be a full commit SHA" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        ["--pr", "7", "--commit", COMMIT],
        ["--commit", COMMIT, "--earlier", "dry.json"],
        [],
    ],
)
def test_a_dry_run_takes_a_pull_request_or_a_commit(api, cloned, extra: list[str]) -> None:
    """The run before of a range is step 4's: `--earlier` names a pull request's run."""
    api()
    with pytest.raises(SystemExit) as stopped:
        fr.main(["dry-run", "--repo", REPO, *extra])
    assert stopped.value.code == 2
    assert cloned[2] == []


def test_a_dry_run_of_a_commit_without_a_key_clones_nothing(
    monkeypatch: pytest.MonkeyPatch, cloned, capsys
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert fr.main(["dry-run", "--repo", REPO, "--commit", COMMIT]) == 2
    assert cloned[2] == []
    assert capsys.readouterr().out.startswith(
        "conventions: no verdict (ANTHROPIC_API_KEY is not set)"
    )
