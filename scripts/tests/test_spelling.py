"""The spelling check (C79, coordinate-core 0.5.1 step 4, .github#18): `spelling.yml` runs a pinned
codespell with its en-GB_to_en-US dictionary over the paths its caller names, wherever C79 reaches:
hidden directories, possessives and identifiers included. This repository's `ci` calls it over its
own files. The tests run the workflow's own step, with `uvx` replaced by the codespell of the test
environment, which must be the version the workflow pins."""

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import codespell_lib
import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SPELLING = (WORKFLOWS / "spelling.yml").read_text()
CI = (WORKFLOWS / "ci.yml").read_text()

# The British spellings the tests plant; the inline ignores keep this file out of the check.
ORG_GB = "organisation"  # codespell:ignore
ORGS_GB = "organisations"  # codespell:ignore
LABELED_GB = "labelled"  # codespell:ignore
BEHAVIOR_GB = "behaviour"  # codespell:ignore

UVX = """\
#!/bin/sh
# uvx as the workflow calls it: --no-config, then the pinned codespell.
[ "$1" = "--no-config" ] || { echo "uvx: --no-config missing" >&2; exit 90; }
[ "$2" = "codespell@$CODESPELL_VERSION" ] || { echo "uvx: unpinned $2" >&2; exit 91; }
shift 2
exec "$PYTHON" -m codespell_lib "$@"
"""


def step(name: str) -> str:
    """The `run:` script of the step `name` of spelling.yml."""
    block = SPELLING.split(f"- name: {name}\n", 1)[1]
    lines = block.split("        run: |\n", 1)[1].splitlines()
    script = []
    for line in lines:
        if line.strip() and not line.startswith("          "):
            break
        script.append(line[10:])
    return "\n".join(script) + "\n"


def check(tmp_path: Path, paths: str, ignore_words: str = "cancelled") -> tuple[int, str]:
    """Run the codespell step in a caller's checkout `tmp_path/caller`: exit code and output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uvx = bin_dir / "uvx"
    uvx.write_text(UVX)
    uvx.chmod(uvx.stat().st_mode | stat.S_IXUSR)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PYTHON": sys.executable,
        "CODESPELL_VERSION": codespell_lib.__version__,
        "PATHS": paths,
        "IGNORE_WORDS": ignore_words,
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_WORKSPACE": str(tmp_path / "caller"),
    }
    done = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step("codespell")],
        cwd=tmp_path / "caller",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


@pytest.fixture
def caller(tmp_path: Path) -> Path:
    """A caller's checkout: a hidden .claude, rules and code, all in American English."""
    repo = tmp_path / "caller"
    (repo / ".claude" / "commands").mkdir(parents=True)
    (repo / ".claude" / "commands" / "adopt.md").write_text("A labeled issue.\n")
    (repo / "rules").mkdir()
    (repo / "rules" / "workspace.md").write_text("- G4 the organization's settings.\n")
    (repo / "src").mkdir()
    (repo / "src" / "gate.py").write_text(
        "def test_the_organizations_behavior():\n"
        "    organizationName = 1\n"
        "    return '${{ !cancelled() }}', organizationName\n"
    )
    return repo


def test_spelling_runs_as_a_called_job_only() -> None:
    triggers = SPELLING.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_call:" in triggers
    assert "pull_request" not in triggers
    assert "\npermissions:\n  contents: read\n" in SPELLING


def test_the_inputs_reach_the_script_through_its_environment() -> None:
    for line in SPELLING.splitlines():
        if "${{ inputs." in line:
            assert re.match(r"^ +[A-Z_]+: \$\{\{ inputs\.[a-z-]+ \}\}$", line), line


def test_actions_are_pinned_to_commits_and_the_checkout_keeps_no_token() -> None:
    uses = re.findall(r"uses: (\S+)( # v[\d.]+)?", SPELLING)
    assert uses
    for ref, version in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
        assert version, ref
    assert "persist-credentials: false" in SPELLING


def test_the_workflow_pins_the_codespell_of_the_tests() -> None:
    assert f"codespell@{codespell_lib.__version__} " in SPELLING


def test_american_spelling_and_githubs_cancelled_pass(tmp_path: Path, caller: Path) -> None:
    code, out = check(tmp_path, ".claude rules src")
    assert code == 0, out


@pytest.mark.parametrize(
    ("path", "text", "word"),
    [
        ("rules/workspace.md", f"- G4 the {ORG_GB}.\n", ORG_GB),
        ("rules/workspace.md", f"- G4 the {ORG_GB}'s settings.\n", ORG_GB),
        (".claude/commands/adopt.md", f"A {LABELED_GB} issue.\n", LABELED_GB),
        ("src/gate.py", f"def test_the_{ORGS_GB}():\n    pass\n", ORGS_GB),
        ("src/gate.py", f"{ORG_GB}Name = 1\n", ORG_GB),
        ("src/gate.py", f"# Cancelled by the human's {BEHAVIOR_GB}.\n", BEHAVIOR_GB),
    ],
)
def test_british_spelling_fails_wherever_c79_reaches(
    tmp_path: Path, caller: Path, path: str, text: str, word: str
) -> None:
    (caller / path).write_text(text)
    code, out = check(tmp_path, ".claude rules src")
    assert code != 0, out
    assert f"{path}:" in out
    assert f"{word} ==> " in out


def test_the_callers_codespell_config_is_not_read(tmp_path: Path, caller: Path) -> None:
    rc = f"[codespell]\nskip = *\nignore-words-list = {BEHAVIOR_GB}\n"
    (caller / ".codespellrc").write_text(rc)
    (caller / "setup.cfg").write_text("[codespell]\nskip = *\n")
    (caller / "pyproject.toml").write_text('[tool.codespell]\nskip = "*"\n')
    (caller / "rules" / "workspace.md").write_text(f"The {BEHAVIOR_GB}.\n")
    code, out = check(tmp_path, ".claude rules src")
    assert code != 0, out
    assert f"{BEHAVIOR_GB} ==> " in out


def test_ignore_words_come_from_the_caller(tmp_path: Path, caller: Path) -> None:
    (caller / "rules" / "workspace.md").write_text(f"The {BEHAVIOR_GB}.\n")
    code, out = check(tmp_path, ".claude rules src", ignore_words=f"cancelled,{BEHAVIOR_GB}")
    assert code == 0, out


def test_a_path_that_does_not_exist_fails(tmp_path: Path, caller: Path) -> None:
    code, out = check(tmp_path, "rules docs CLAUDE.md")
    assert code != 0, out
    assert "docs does not exist" in out
    assert "CLAUDE.md does not exist" in out


def test_no_path_fails(tmp_path: Path, caller: Path) -> None:
    code, out = check(tmp_path, "  ")
    assert code != 0, out
    assert "names no path" in out


def test_ci_calls_the_spelling_check_over_this_repository() -> None:
    job = CI.split("\n  spelling:\n", 1)[1].split("\n  ci:\n", 1)[0]
    assert "uses: ./.github/workflows/spelling.yml" in job
    assert "paths: README.md .github scripts" in job


def test_the_required_ci_fails_when_the_spelling_check_did_not_pass() -> None:
    job = CI.split("\n  ci:\n", 1)[1]
    assert "needs: spelling" in job
    assert "if: ${{ !cancelled() }}" in job
    assert "needs.spelling.result" in job
    assert f"--with codespell=={codespell_lib.__version__}" in job


def test_the_readme_shows_the_caller() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "uses: xippios/.github/.github/workflows/spelling.yml@main" in readme
