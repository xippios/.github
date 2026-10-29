"""Tests for family_review.py, offline: a fake Messages client, real temporary git repositories.

The fake client returns the SDK's own ``Message`` objects and raises its own error classes; no
test needs a key or the network. ``gh`` is a fake on PATH that writes fixed JSON.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import anthropic
import family_review as fr
import httpx2
import pytest

REPO = "xippios/sdk-usda-psd"
BASE = "b" * 40
HEAD = "c" * 40
DIFF = "diff --git a/src/pkg/mod.py b/src/pkg/mod.py\n+SECRET_CONTENT_MARKER = 1\n"
# Built at run time, so no key-shaped literal sits in the repository.
FAKE_KEY = "sk-ant-" + "api03-" + "Zx9" * 8
FAKE_TOKEN = "ghp_" + "A1b2" * 9
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


# --- the fake client ---------------------------------------------------------------------


def message(content, stop_reason="tool_use", usage=(10, 1, 0, 0), stop_details=None):
    """A Message as the SDK returns it; usage is (input, output, cache write, cache read)."""
    data = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": fr.MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "stop_details": stop_details,
        "usage": {
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "cache_creation_input_tokens": usage[2],
            "cache_read_input_tokens": usage[3],
        },
    }
    return anthropic.types.Message.model_validate(data)


def call(tool_id, name, tool_input):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


THINKING = {"type": "thinking", "thinking": "", "signature": "sig-1"}


def verdict(value="ready", findings=()):
    return call("toolu_v", "submit_verdict", {"verdict": value, "findings": list(findings)})


def finding(file="src/pkg/mod.py", line=2, blocking=False, text="A finding."):
    return {"file": file, "line": line, "blocking": blocking, "text": text}


class FakeMessages:
    """``messages.create`` that records each request and plays a script."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def create(self, **kwargs):
        # The loop appends to its list afterwards: keep this request's view of it.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)


def status_error(cls, status, text):
    body = {"type": "error", "error": {"type": "error_type", "message": text}}
    response = httpx2.Response(status, request=REQUEST, headers={"request-id": "req_test1"})
    return cls(f"Error code: {status} - {body}", response=response, body=body)


# --- fixtures ----------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A prepared workspace: .review with its meta.json, .sdk-core-main, a source file."""
    ws = tmp_path / "ws"
    review = ws / ".review"
    review.mkdir(parents=True)
    (review / "diff.patch").write_text(DIFF)
    (review / "log.txt").write_text(f"commit {HEAD}\n")
    meta = {"repo": REPO, "pr": 11, "base": BASE, "head": HEAD}
    (review / "meta.json").write_text(json.dumps(meta))
    core = ws / ".sdk-core-main"
    (core / "docs" / "adr").mkdir(parents=True)
    for doc in fr.DOCUMENTS:
        (core / doc).write_text(f"# {doc}\n")
    (core / "docs" / "adr" / "0001-layering.md").write_text("# ADR 1\n")
    source = ws / "src" / "pkg"
    source.mkdir(parents=True)
    (source / "mod.py").write_text("import os\nVALUE = 1\n")
    return ws


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """Install a fake client for a script of responses; the key is a dummy."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-tests")

    def install(*script):
        client = FakeClient(script)
        monkeypatch.setattr(fr, "make_client", lambda: client)
        return client

    return install


def run_review(workspace: Path, tmp_path: Path, *extra: str) -> tuple[int, dict]:
    out = tmp_path / "verdict.json"
    code = fr.main(
        [
            "review",
            "--workspace",
            str(workspace),
            "--review",
            str(workspace / ".review"),
            "--docs",
            str(workspace / ".sdk-core-main"),
            "--out",
            str(out),
            *extra,
        ]
    )
    return code, json.loads(out.read_text())


# --- the loop ----------------------------------------------------------------------------


def test_two_tool_calls_then_the_verdict(
    workspace: Path, tmp_path: Path, api, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    first = message(
        [
            THINKING,
            call("toolu_1", "read_file", {"path": ".review/diff.patch"}),
            call("toolu_2", "grep", {"pattern": "VALUE"}),
        ],
        usage=(100, 10, 1000, 0),
    )
    client = api(
        first,
        message([call("toolu_3", "list_files", {"pattern": "src/**"})], usage=(50, 20, 30, 1000)),
        message([verdict("ready", [finding()])], usage=(10, 30, 5, 1030)),
    )
    code, result = run_review(workspace, tmp_path)

    line = (
        "family-review: verdict=ready findings=1 blocking=0 turns=3 tool_calls=4 input=160 "
        "cache_write=1035 cache_read=2030 output=60 cost_estimate_usd=0.01 "
        "model=claude-opus-5-5 effort=high"
    )
    assert code == 0
    assert result["verdict"] == "ready"
    assert result["findings"] == [finding()]
    assert result["usage"] == {
        "input_tokens": 160,
        "cache_creation_input_tokens": 1035,
        "cache_read_input_tokens": 2030,
        "output_tokens": 60,
    }
    assert result["turns"] == 3
    assert result["tool_calls"] == {"grep": 1, "list_files": 1, "read_file": 1, "submit_verdict": 1}
    assert result["model"] == "claude-opus-5-5"
    assert result["effort"] == "high"
    assert result["cost_estimate_usd"] == pytest.approx(0.0074, abs=1e-4)
    assert result["summary"] == line
    captured = capsys.readouterr()
    assert captured.out == line + "\n"
    assert summary.read_text() == line + "\n"
    # The log carries no file content and no tool result.
    assert "SECRET_CONTENT_MARKER" not in captured.out + captured.err

    # The assistant turn goes back verbatim, thinking included; the results in one message.
    second = client.messages.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"] is first.content
    assert second[1]["content"][0].type == "thinking"
    results = second[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_1", "toolu_2"]
    assert all(r["type"] == "tool_result" and "is_error" not in r for r in results)
    assert "     2\t+SECRET_CONTENT_MARKER = 1" in results[0]["content"]
    assert "src/pkg/mod.py:2: VALUE = 1" in results[1]["content"]
    third = client.messages.requests[2]["messages"]
    assert third[-1]["content"][0]["content"] == "src/pkg/mod.py"


def test_the_request_caches_the_prefix_and_forces_nothing(
    workspace: Path, tmp_path: Path, api
) -> None:
    client = api(message([verdict()]))
    run_review(workspace, tmp_path)
    request = client.messages.requests[0]

    assert request["cache_control"] == {"type": "ephemeral"}
    system = request["system"]
    assert [block["type"] for block in system] == ["text"] * 4
    assert system[-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in block for block in system[:-1])
    assert f"Pull request {REPO}#11: base {BASE}, head" in system[0]["text"]
    assert HEAD in system[0]["text"]
    assert ".claude-pr" not in system[0]["text"]
    assert "the action" not in system[0]["text"]
    assert "at most 120 turns" in system[0]["text"]
    labels = [block["text"].split("\n", 1)[0] for block in system[1:]]
    assert labels == [f"The file `.sdk-core-main/{doc}`:" for doc in fr.DOCUMENTS]
    assert request["model"] == "claude-opus-5-5"
    assert request["max_tokens"] == 16000
    assert request["output_config"] == {"effort": "high"}
    for absent in ("thinking", "tool_choice", "betas", "temperature"):
        assert absent not in request
    names = [tool["name"] for tool in request["tools"]]
    assert names == ["read_file", "list_files", "grep", "submit_verdict"]
    for tool in request["tools"]:
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False
    first = request["messages"][0]
    assert first["role"] == "user"
    assert "`.review/`" in first["content"]
    assert "`.sdk-core-main/`" in first["content"]


def test_options_reach_the_request(workspace: Path, tmp_path: Path, api) -> None:
    client = api(message([verdict()]))
    run_review(workspace, tmp_path, "--model", "claude-opus-5", "--effort", "medium")
    request = client.messages.requests[0]
    assert request["model"] == "claude-opus-5"
    assert request["output_config"] == {"effort": "medium"}


def test_end_turn_without_a_verdict_is_reprompted_once(
    workspace: Path, tmp_path: Path, api
) -> None:
    text = {"type": "text", "text": "Done reading."}
    client = api(message([text], "end_turn"), message([verdict("not ready")]))
    code, result = run_review(workspace, tmp_path)
    assert code == 1
    assert result["verdict"] == "not ready"
    last = client.messages.requests[1]["messages"]
    assert last[-1] == {"role": "user", "content": "Call submit_verdict now."}


def test_end_turn_twice_is_no_verdict(workspace: Path, tmp_path: Path, api, capsys) -> None:
    text = {"type": "text", "text": "Done."}
    client = api(message([text], "end_turn"), message([text], "end_turn"))
    code, result = run_review(workspace, tmp_path)
    assert code == 2
    assert result["verdict"] is None
    assert "without calling submit_verdict" in result["reason"]
    assert len(client.messages.requests) == 2
    out = capsys.readouterr().out
    assert out.startswith("family-review: no verdict (the model ended its turn twice")
    assert "turns=2 " in out


def test_max_tokens_is_no_verdict(workspace: Path, tmp_path: Path, api) -> None:
    api(message([call("toolu_1", "read_file", {"path": "x"})], "max_tokens"))
    code, result = run_review(workspace, tmp_path)
    assert code == 2
    assert result["reason"] == "the response reached max_tokens (16000)"


def test_a_refusal_is_no_verdict_with_its_category(workspace: Path, tmp_path: Path, api) -> None:
    details = {"type": "refusal", "category": "cyber", "explanation": None}
    api(message([], "refusal", stop_details=details))
    code, result = run_review(workspace, tmp_path)
    assert code == 2
    assert result["reason"] == "the model refused, category cyber"
    assert result["summary"].startswith("family-review: no verdict (the model refused")


def test_the_turn_cap_is_no_verdict(workspace: Path, tmp_path: Path, api) -> None:
    reads = [
        message([call(f"toolu_{i}", "read_file", {"path": "src/pkg/mod.py"})]) for i in range(3)
    ]
    client = api(*reads)
    code, result = run_review(workspace, tmp_path, "--max-turns", "2")
    assert code == 2
    assert result["reason"] == "the turn cap of 2 was reached"
    assert result["turns"] == 2
    assert len(client.messages.requests) == 2


def test_an_invalid_verdict_is_answered_as_an_error(workspace: Path, tmp_path: Path, api) -> None:
    bad = call("toolu_bad", "submit_verdict", {"verdict": "maybe", "findings": []})
    client = api(message([bad]), message([verdict()]))
    code, result = run_review(workspace, tmp_path)
    assert code == 0
    answer = client.messages.requests[1]["messages"][-1]["content"][0]
    assert answer["is_error"] is True
    assert "verdict must be ready or not ready" in answer["content"]
    assert result["tool_calls"] == {"submit_verdict": 2}


def test_a_blocking_finding_makes_it_not_ready(workspace: Path, tmp_path: Path, api) -> None:
    api(message([verdict("ready", [finding(blocking=True)])]))
    code, result = run_review(workspace, tmp_path)
    assert code == 1
    assert result["verdict"] == "not ready"
    assert result["summary"].startswith("family-review: verdict=not ready findings=1 blocking=1 ")


def test_no_key_is_no_verdict_and_no_client(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(fr, "make_client", lambda: pytest.fail("no client without a key"))
    code, result = run_review(workspace, tmp_path)
    assert code == 2
    assert result["verdict"] is None
    out = capsys.readouterr().out
    assert out.startswith("family-review: no verdict (ANTHROPIC_API_KEY is not set) turns=0 ")


def test_missing_material_is_no_verdict(workspace: Path, tmp_path: Path, api) -> None:
    api()
    (workspace / ".sdk-core-main" / "docs" / "conventions.md").unlink()
    code, result = run_review(workspace, tmp_path)
    assert code == 2
    assert (
        result["reason"] == ".sdk-core-main/docs/conventions.md is missing; the review cannot run"
    )


CREDIT = (
    "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing "
    "to upgrade or purchase credits."
)


@pytest.mark.parametrize(
    ("error", "name"),
    [
        (
            status_error(anthropic.AuthenticationError, 401, "invalid x-api-key"),
            "AuthenticationError",
        ),
        (
            status_error(anthropic.PermissionDeniedError, 403, "not allowed"),
            "PermissionDeniedError",
        ),
        (status_error(anthropic.BadRequestError, 400, CREDIT), "BadRequestError"),
        (status_error(anthropic.RateLimitError, 429, "rate limited"), "RateLimitError"),
        (status_error(anthropic.InternalServerError, 500, "internal"), "InternalServerError"),
        (status_error(anthropic.APIStatusError, 418, "teapot"), "APIStatusError"),
        (anthropic.APIConnectionError(request=REQUEST), "APIConnectionError"),
        (anthropic.APITimeoutError(request=REQUEST), "APITimeoutError"),
    ],
)
def test_an_api_error_is_no_verdict_with_its_class(
    workspace: Path, tmp_path: Path, api, capsys, error, name
) -> None:
    api(error)
    code, result = run_review(workspace, tmp_path)
    out = capsys.readouterr().out
    assert code == 2
    assert result["verdict"] is None
    assert out.startswith(f"family-review: no verdict (API error: {name}: ")
    assert "turns=0 tool_calls=0 input=0 " in out
    assert len(result["reason"]) <= len(f"API error: {name}: ") + fr.ERROR_CHARS + 30


def test_the_credit_message_reaches_the_summary_readable(
    workspace: Path, tmp_path: Path, api, capsys
) -> None:
    api(status_error(anthropic.BadRequestError, 400, CREDIT))
    run_review(workspace, tmp_path)
    out = capsys.readouterr().out
    assert f"(API error: BadRequestError: {CREDIT} (request req_test1)) turns=0" in out


def test_an_api_error_message_is_redacted_and_cut(workspace: Path, tmp_path: Path, api, capsys):
    api(status_error(anthropic.BadRequestError, 400, f"bad key {FAKE_KEY} " + "x" * 500))
    code, result = run_review(workspace, tmp_path)
    out = capsys.readouterr().out
    assert code == 2
    assert FAKE_KEY not in out
    assert "[redacted]" in out
    message = result["reason"].removeprefix("API error: BadRequestError: ")
    assert len(message.split(" (request ")[0]) == fr.ERROR_CHARS


def test_an_error_after_some_turns_keeps_their_usage(workspace: Path, tmp_path: Path, api) -> None:
    api(
        message([call("toolu_1", "list_files", {"pattern": "**"})], usage=(7, 3, 0, 0)),
        status_error(anthropic.RateLimitError, 429, "slow down"),
    )
    code, result = run_review(workspace, tmp_path)
    assert code == 2
    assert result["turns"] == 1
    assert result["usage"]["input_tokens"] == 7


def test_a_key_in_a_finding_is_redacted(
    workspace: Path, tmp_path: Path, api, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    leaky = finding(file=f"conf/{FAKE_TOKEN}.txt", text=f"The key {FAKE_KEY} is committed.")
    api(message([verdict("not ready", [leaky])]))
    code, result = run_review(workspace, tmp_path)
    assert code == 1
    written = (tmp_path / "verdict.json").read_text()
    assert FAKE_KEY not in written
    assert FAKE_TOKEN not in written
    assert result["findings"][0]["text"] == "The key [redacted] is committed."
    assert result["findings"][0]["file"] == "conf/[redacted].txt"
    out = capsys.readouterr().out
    assert FAKE_KEY not in out + summary.read_text()


def test_redact_covers_the_verdict_steps_patterns() -> None:
    text = f"{FAKE_KEY} {FAKE_TOKEN} gho_abc ghs_abc github_pat_11AB_cd"
    assert fr.redact(text) == " ".join(["[redacted]"] * 5)


# --- the sandbox -------------------------------------------------------------------------


@pytest.fixture
def sandbox(workspace: Path, tmp_path: Path) -> fr.Sandbox:
    (tmp_path / "outside.txt").write_text("OUTSIDE_CONTENT\n")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("[core]\nGIT_CONTENT\n")
    (workspace / "sub" / ".git").mkdir(parents=True)
    (workspace / "sub" / ".git" / "HEAD").write_text("GIT_CONTENT\n")
    for name in (".envrc", ".env", ".env.local"):
        (workspace / name).write_text("ENV_CONTENT\n")
    (workspace / "nested").mkdir()
    (workspace / "nested" / ".env").write_text("ENV_CONTENT\n")
    (workspace / "passwd-link").symlink_to("/etc/passwd")
    (workspace / "out-link").symlink_to(tmp_path / "outside.txt")
    (workspace / "outdir").symlink_to(tmp_path)
    (workspace / "git-link").symlink_to(workspace / ".git" / "config")
    (workspace / "ok-link").symlink_to(workspace / "src" / "pkg" / "mod.py")
    (workspace / ".sdk-gates" / "scripts").mkdir(parents=True)
    (workspace / ".sdk-gates" / "scripts" / "family_review.py").write_text("GATES_CONTENT\n")
    return fr.Sandbox(workspace, hidden=[workspace / ".sdk-gates"])


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "src/../../outside.txt",
        "/etc/passwd",
        ".git/config",
        "sub/.git/HEAD",
        "./.git/config",
        ".envrc",
        ".env",
        ".env.local",
        "nested/.env",
        "passwd-link",
        "out-link",
        "outdir/outside.txt",
        "git-link",
        ".sdk-gates/scripts/family_review.py",
        "",
    ],
)
def test_the_sandbox_refuses(sandbox: fr.Sandbox, path: str) -> None:
    answer, is_error = fr.serve(sandbox, "read_file", {"path": path})
    assert is_error
    for content in ("OUTSIDE_CONTENT", "GIT_CONTENT", "ENV_CONTENT", "GATES_CONTENT", "root:"):
        assert content not in answer


def test_the_sandbox_refuses_an_absolute_path_outside(sandbox: fr.Sandbox, tmp_path: Path) -> None:
    answer, is_error = fr.serve(sandbox, "read_file", {"path": str(tmp_path / "outside.txt")})
    assert is_error
    assert answer == "refused: the path is outside the working directory"


def test_the_sandbox_reads_inside(sandbox: fr.Sandbox, workspace: Path) -> None:
    for path in ("src/pkg/mod.py", "./src/pkg/mod.py", str(workspace / "src/pkg/mod.py")):
        answer, is_error = fr.serve(sandbox, "read_file", {"path": path})
        assert not is_error
        assert answer == "src/pkg/mod.py: lines 1 to 2 of 2\n     1\timport os\n     2\tVALUE = 1"
    answer, is_error = fr.serve(sandbox, "read_file", {"path": "ok-link"})
    assert not is_error
    assert "VALUE = 1" in answer


def test_list_and_grep_skip_what_the_sandbox_refuses(sandbox: fr.Sandbox) -> None:
    listing, is_error = fr.serve(sandbox, "list_files", {"pattern": "**"})
    assert not is_error
    paths = listing.splitlines()
    assert "src/pkg/mod.py" in paths
    assert "ok-link" in paths
    assert ".review/diff.patch" in paths
    for refused in (".git/config", "sub/.git/HEAD", ".envrc", ".env", ".env.local", "nested/.env"):
        assert refused not in paths
    for refused in ("passwd-link", "out-link", "git-link", ".sdk-gates/scripts/family_review.py"):
        assert refused not in paths
    assert not any(p.startswith("outdir/") for p in paths)
    for pattern in ("OUTSIDE_CONTENT", "GIT_CONTENT", "ENV_CONTENT", "GATES_CONTENT", "root:"):
        answer, is_error = fr.serve(sandbox, "grep", {"pattern": pattern})
        assert not is_error
        assert answer.startswith("[0 matches in ")


@pytest.mark.parametrize(
    ("name", "args", "message"),
    [
        ("read_file", {"path": "src"}, "not a file"),
        ("read_file", {"path": "missing.txt"}, "no such file"),
        ("read_file", {"path": "src/pkg/mod.py", "start_line": "x"}, "start_line must be"),
        ("read_file", {}, "path must be a string"),
        ("list_files", {"pattern": "../*"}, "may not leave"),
        ("list_files", {"pattern": "/etc/*"}, "a pattern is a glob"),
        ("grep", {"pattern": "(", "regex": True}, "not a valid regular expression"),
        ("grep", {"pattern": "x", "regex": "yes"}, "regex must be"),
        ("grep", {"pattern": ""}, "the pattern is empty"),
        ("delete_file", {"path": "x"}, "there is no tool"),
        ("read_file", ["x"], "the input is not an object"),
    ],
)
def test_a_tool_never_raises(sandbox: fr.Sandbox, name: str, args, message: str) -> None:
    answer, is_error = fr.serve(sandbox, name, args)
    assert is_error
    assert message in answer


def test_an_unexpected_failure_is_a_tool_error(
    sandbox: fr.Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args):
        raise RuntimeError("boom with CONTENT")

    monkeypatch.setattr(fr, "_text", broken)
    answer, is_error = fr.serve(sandbox, "read_file", {"path": "src/pkg/mod.py"})
    assert is_error
    assert answer == "the tool failed: RuntimeError"


def test_binary_files_are_refused_and_skipped(sandbox: fr.Sandbox, workspace: Path) -> None:
    (workspace / "blob.bin").write_bytes(b"VALUE\x00\x01")
    answer, is_error = fr.serve(sandbox, "read_file", {"path": "blob.bin"})
    assert is_error
    assert "binary" in answer
    answer, _ = fr.serve(sandbox, "grep", {"pattern": "VALUE"})
    assert "blob.bin" not in answer.split("[")[0]
    assert "1 binary or large files skipped" in answer


def test_the_scripts_own_checkout_is_hidden_only_inside_the_workspace(tmp_path: Path) -> None:
    own = Path(fr.__file__).resolve().parents[1]
    assert fr._own_checkout(tmp_path) == []
    assert fr._own_checkout(own) == []
    assert fr._own_checkout(own.parent) == [own]


# --- the caps ----------------------------------------------------------------------------


def test_read_file_caps_lines(workspace: Path) -> None:
    sandbox = fr.Sandbox(workspace)
    (workspace / "long.txt").write_text("".join(f"line {n}\n" for n in range(1, 2501)))
    answer, _ = fr.serve(sandbox, "read_file", {"path": "long.txt", "max_lines": 5000})
    lines = answer.splitlines()
    assert lines[0] == "long.txt: lines 1 to 2000 of 2500"
    assert lines[2000] == "  2000\tline 2000"
    assert lines[-1] == "[cut: lines 1 to 2000 of 2500; continue with start_line=2001]"
    answer, _ = fr.serve(sandbox, "read_file", {"path": "long.txt", "start_line": 2001})
    assert answer.splitlines()[0] == "long.txt: lines 2001 to 2500 of 2500"
    assert answer.splitlines()[-1] == "  2500\tline 2500"
    answer, _ = fr.serve(
        sandbox, "read_file", {"path": "long.txt", "start_line": 9, "max_lines": 2}
    )
    assert answer.splitlines() == [
        "long.txt: lines 9 to 10 of 2500",
        "     9\tline 9",
        "    10\tline 10",
        "[cut: lines 9 to 10 of 2500; continue with start_line=11]",
    ]
    answer, _ = fr.serve(sandbox, "read_file", {"path": "long.txt", "start_line": 3000})
    assert answer == "long.txt: 2500 lines; start_line 3000 is past the end"


def test_read_file_caps_bytes(workspace: Path) -> None:
    sandbox = fr.Sandbox(workspace)
    (workspace / "wide.txt").write_text(("y" * 200 + "\n") * 1000)
    answer, _ = fr.serve(sandbox, "read_file", {"path": "wide.txt"})
    assert len(answer.encode()) <= fr.MAX_ANSWER_BYTES
    assert answer.splitlines()[-1].startswith("[cut: lines 1 to ")
    (workspace / "huge-line.txt").write_text("z" * 100_000 + "\nsecond\n")
    answer, _ = fr.serve(sandbox, "read_file", {"path": "huge-line.txt"})
    assert len(answer.encode()) <= fr.MAX_ANSWER_BYTES
    assert "[line cut]" in answer
    assert answer.splitlines()[-1].endswith("continue with start_line=2]")


def test_list_files_caps_entries(workspace: Path) -> None:
    sandbox = fr.Sandbox(workspace)
    many = workspace / "many"
    many.mkdir()
    for n in range(600):
        (many / f"f{n:03}.txt").write_text("x\n")
    answer, _ = fr.serve(sandbox, "list_files", {"pattern": "many/*.txt"})
    lines = answer.splitlines()
    assert len(lines) == 501
    assert lines[0] == "many/f000.txt"
    assert lines[499] == "many/f499.txt"
    assert lines[-1] == "[600 files match; the first 500 are shown]"
    answer, _ = fr.serve(sandbox, "list_files", {"pattern": "nothing/*"})
    assert answer == "no file matches"


def test_grep_caps_matches_and_time(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = fr.Sandbox(workspace)
    (workspace / "hits.txt").write_text("hit\n" * 300)
    answer, _ = fr.serve(sandbox, "grep", {"pattern": "hit", "glob": "*.txt"})
    lines = answer.splitlines()
    assert len(lines) == 201
    assert lines[0] == "hits.txt:1: hit"
    assert lines[-1] == "[200 matches in 1 files searched; cut at 200 matches]"
    answer, _ = fr.serve(sandbox, "grep", {"pattern": "hit", "glob": "hits.txt", "max_results": 10})
    assert answer.splitlines()[-1] == "[10 matches in 1 files searched; cut at 10 matches]"
    answer, _ = fr.serve(sandbox, "grep", {"pattern": r"^VAL\w+ = \d$", "regex": True})
    assert answer.splitlines()[0] == "src/pkg/mod.py:2: VALUE = 1"
    monkeypatch.setattr(fr, "GREP_SECONDS", -1.0)
    answer, _ = fr.serve(sandbox, "grep", {"pattern": "hit"})
    assert "the search stopped after" in answer


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("**/*.py", "a.py", True),
        ("**/*.py", "x/y/a.py", True),
        ("*.py", "x/a.py", False),
        ("src/**", "src/a/b.txt", True),
        ("docs/adr/*", "docs/adr/0001.md", True),
        ("docs/adr/*", "docs/adr/sub/0001.md", False),
        ("f?.txt", "f1.txt", True),
        ("f[0-9].txt", "f7.txt", True),
        ("f[!0-9].txt", "f7.txt", False),
        ("a+b.txt", "a+b.txt", True),
        ("./src/*.py", "src/a.py", True),
    ],
)
def test_glob_regex(pattern: str, path: str, matches: bool) -> None:
    assert bool(fr.glob_regex(pattern).fullmatch(path)) is matches


# --- prepare -----------------------------------------------------------------------------


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


def commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    for path, content in files.items():
        target = repo / path
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


BASE_FILES = {
    "src/pkg/mod.py": "VALUE = 1\n",
    "docs/conventions.md": "# conventions, base\n",
    "docs/adr/0001-layering.md": "# ADR 1, base\n",
}
HEAD_CHANGES = {
    "src/pkg/mod.py": "VALUE = 2\n",
    "docs/conventions.md": "# conventions, the branch\n",
    "docs/adr/0002-new.md": "# ADR 2, the branch\n",
}


def make_checkout(root: Path, head_changes: dict[str, str | None]) -> tuple[Path, str, str]:
    """A repository at its head, with sdk-core's main beside it in .sdk-core-main."""
    ws = root / "ws"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    base = commit(ws, BASE_FILES, "base")
    head = commit(ws, head_changes, "feat: the change\n\nWith a body.")
    core = ws / ".sdk-core-main"
    (core / "docs" / "adr").mkdir(parents=True)
    for doc in fr.DOCUMENTS:
        (core / doc).write_text(f"# {doc}, main\n")
    return ws, base, head


PR_JSON = '{"title": "feat: the change", "body": "Body.", "author": {"login": "johan"}}\n'
CHECKS_JSON = '[{"name": "ci", "state": "SUCCESS"}]\n'


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A gh on PATH: `pr view` prints PR_JSON (or the SHAs), `pr checks` CHECKS_JSON or 8."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pr.json").write_text(PR_JSON)
    (bin_dir / "checks.json").write_text(CHECKS_JSON)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'here=$(dirname "$0")\n'
        'printf "%s\\n" "$*" >> "$here/calls"\n'
        'case "$1 $2 $*" in\n'
        '  "pr view "*baseRefOid*) cat "$here/shas.json" ;;\n'
        '  "pr view "*) cat "$here/pr.json" ;;\n'
        '  "pr checks "*) [ -f "$here/checks-fail" ] && exit 8; cat "$here/checks.json" ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


def prepare(repo: str, ws: Path, base: str, head: str) -> int:
    return fr.main(
        [
            "prepare",
            "--repo",
            repo,
            "--pr",
            "7",
            "--base-sha",
            base,
            "--head-sha",
            head,
            "--workspace",
            str(ws),
        ]
    )


def test_prepare_writes_the_review_material(
    tmp_path: Path, fake_gh: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    ws, base, head = make_checkout(tmp_path, HEAD_CHANGES)
    (ws / ".review").mkdir()
    (ws / ".review" / "planted.txt").write_text("from the pull request\n")

    assert prepare(REPO, ws, base, head) == 0
    review = ws / ".review"
    assert sorted(p.name for p in review.iterdir()) == [
        "checks.json",
        "diff.patch",
        "log.txt",
        "meta.json",
        "pr.json",
    ]
    diff = (review / "diff.patch").read_text()
    assert "-VALUE = 1\n+VALUE = 2" in diff
    assert "docs/adr/0002-new.md" in diff
    log = (review / "log.txt").read_text()
    assert log.startswith(f"commit {head}\nAuthor: test <test@example.invalid>\nDate:   ")
    assert "\n\nfeat: the change\n\nWith a body.\n" in log
    assert (review / "pr.json").read_text() == PR_JSON
    assert (review / "checks.json").read_text() == CHECKS_JSON
    meta = json.loads((review / "meta.json").read_text())
    assert meta == {"repo": REPO, "pr": 7, "base": base, "head": head}
    calls = (fake_gh / "calls").read_text().splitlines()
    assert calls == [
        f"pr view 7 --repo {REPO} --json title,body,author,comments,files",
        (
            f"pr checks 7 --repo {REPO} --json "
            "name,state,bucket,workflow,description,startedAt,completedAt,link"
        ),
    ]
    # Not sdk-core: the family documents stay main's, whatever the pull request changes.
    core = ws / ".sdk-core-main" / "docs"
    assert (core / "conventions.md").read_text() == "# docs/conventions.md, main\n"
    assert not (core / "adr" / "0002-new.md").exists()
    out = capsys.readouterr().out
    assert "family-review: .review/diff.patch " in out
    assert "the pull request's branch" not in out
    assert not summary.exists()


def test_prepare_falls_back_when_the_checks_fail(tmp_path: Path, fake_gh: Path) -> None:
    (fake_gh / "checks-fail").write_text("")
    ws, base, head = make_checkout(tmp_path, HEAD_CHANGES)
    assert prepare(REPO, ws, base, head) == 0
    assert (ws / ".review" / "checks.json").read_text() == fr.CHECKS_FALLBACK


def test_an_sdk_core_pull_request_reads_its_changed_documents(
    tmp_path: Path, fake_gh: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    ws, base, head = make_checkout(tmp_path, HEAD_CHANGES)
    assert prepare("xippios/sdk-core", ws, base, head) == 0
    core = ws / ".sdk-core-main" / "docs"
    assert (core / "conventions.md").read_text() == "# conventions, the branch\n"
    assert (core / "adr" / "0002-new.md").read_text() == "# ADR 2, the branch\n"
    # Unchanged by the pull request: main's version stays.
    assert (core / "review-checklist.md").read_text() == "# docs/review-checklist.md, main\n"
    notices = [
        "family-review: docs/adr/0002-new.md read from the pull request's branch",
        "family-review: docs/conventions.md read from the pull request's branch",
    ]
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if "branch" in line] == notices
    assert summary.read_text() == "".join(f"{line}\n" for line in notices)


def test_an_sdk_core_pull_request_that_deletes_a_document_cannot_run(
    tmp_path: Path, fake_gh: Path, capsys
) -> None:
    ws, base, head = make_checkout(tmp_path, {"docs/conventions.md": None})
    assert prepare("xippios/sdk-core", ws, base, head) == 2
    assert not (ws / ".sdk-core-main" / "docs" / "conventions.md").exists()
    out = capsys.readouterr().out
    assert "family-review: docs/conventions.md deleted on the pull request's branch" in out
    assert (
        "family-review: .sdk-core-main/docs/conventions.md is missing; the review cannot run" in out
    )


@pytest.mark.parametrize("kind", ["missing", "link"])
def test_prepare_needs_sdk_core_main(tmp_path: Path, fake_gh: Path, capsys, kind: str) -> None:
    ws, base, head = make_checkout(tmp_path, HEAD_CHANGES)
    core = ws / ".sdk-core-main"
    moved = core.rename(tmp_path / "elsewhere")
    if kind == "link":
        core.symlink_to(moved)
    assert prepare(REPO, ws, base, head) == 2
    out = capsys.readouterr().out
    assert "family-review: .sdk-core-main is missing or a link; the review cannot run" in out


def test_prepare_needs_full_shas_without_workdir(tmp_path: Path, fake_gh: Path, capsys) -> None:
    ws, base, _ = make_checkout(tmp_path, HEAD_CHANGES)
    assert prepare(REPO, ws, base, "HEAD") == 2
    assert "base and head must be full commit SHAs" in capsys.readouterr().out


def test_dry_run_prepares_and_reviews(
    tmp_path: Path, fake_gh: Path, api, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    source, base, head = make_checkout(tmp_path, HEAD_CHANGES)
    (fake_gh / "shas.json").write_text(json.dumps({"baseRefOid": base, "headRefOid": head}))

    def clone(repo: str, pr: int, sha: str, workdir: Path) -> None:
        git(tmp_path, "clone", "-q", str(source), str(workdir))
        git(workdir, "checkout", "-q", "--detach", sha)
        shutil.copytree(source / ".sdk-core-main", workdir / ".sdk-core-main")

    monkeypatch.setattr(fr, "clone_pull_request", clone)
    leaky = finding(text=f"Key {FAKE_KEY} here.", blocking=True)
    client = api(
        message([call("toolu_1", "read_file", {"path": ".review/diff.patch"})]),
        message([verdict("not ready", [leaky, finding(file="", line=None)])]),
    )
    out_file = tmp_path / "dry.json"
    code = fr.main(["dry-run", "--repo", REPO, "--pr", "7", "--out", str(out_file)])
    assert code == 1
    out = capsys.readouterr().out.splitlines()
    assert out[-3].startswith("family-review: verdict=not ready findings=2 blocking=1 turns=2 ")
    assert out[-2] == "src/pkg/mod.py:2 [blocking] Key [redacted] here."
    assert out[-1] == "the pull request [non-blocking] A finding."
    answer = client.messages.requests[1]["messages"][-1]["content"][0]["content"]
    assert "+VALUE = 2" in answer
    assert json.loads(out_file.read_text())["verdict"] == "not ready"


def test_dry_run_without_a_key_clones_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(fr, "clone_pull_request", lambda *a: pytest.fail("no clone without a key"))
    assert fr.main(["dry-run", "--repo", REPO, "--pr", "7"]) == 2
    assert capsys.readouterr().out.startswith(
        "family-review: no verdict (ANTHROPIC_API_KEY is not set)"
    )
