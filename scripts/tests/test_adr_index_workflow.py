"""The ADR index check (https://github.com/xippios/coordinate-core/issues/755, .github#46):
`adr-index.yml` fails a pull request whose `docs/adr.md` or `docs/adr.json` differs from what the
caller's own `scripts/adr_index.py` writes from the records in `docs/adr/`, or whose records take a
number twice, and each failure names the script to run. The tests hold the workflow's declaration
and its pins, as test_spelling.py holds those of spelling.yml, and run the workflow's own step in a
caller's checkout whose script stands in for the template's: it writes the list of the records,
and with `--check` writes nothing and exits 1 when the index differs. Like the template's, it
writes nothing and exits 1 in both modes while a record's first line does not read. It checks no
number twice, as an older script might not, and it runs only under `python -I`."""

import json
import os
import re
import stat
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPT = "scripts/adr_index.py"
RUN = f"python3 {SCRIPT}"

STAND_IN = """\
import json
import re
import sys
from pathlib import Path

if not sys.flags.isolated:
    sys.exit("adr_index.py: run without -I")
root = Path(__file__).resolve().parent.parent
names = sorted(p.name for p in (root / "docs" / "adr").glob("*.md"))
unread = [
    name
    for name in names
    if re.match(r"\\d{4}-.+\\.md$", name)
    and not (root / "docs" / "adr" / name).read_text().startswith(f"# ADR-{name[:4]}: ")
]
for name in unread:
    print(f"docs/adr/{name}: the first line does not read")
if unread:
    sys.exit(1)
wanted = {
    "docs/adr.md": "".join(f"- {name}\\n" for name in names),
    "docs/adr.json": json.dumps({"records": names}) + "\\n",
}
stale = [n for n, t in wanted.items() if not (root / n).is_file() or (root / n).read_text() != t]
if "--check" in sys.argv[1:]:
    if stale:
        print(", ".join(stale) + ": stale")
    sys.exit(1 if stale else 0)
for name in stale:
    (root / name).write_text(wanted[name])
"""

PYTHON3 = """\
#!/bin/sh
exec "$PYTHON" "$@"
"""


@cache
def workflow() -> str:
    return (WORKFLOWS / "adr-index.yml").read_text()


def step(name: str) -> str:
    """The `run:` script of the step `name` of adr-index.yml."""
    block = workflow().split(f"- name: {name}\n", 1)[1]
    lines = block.split("        run: |\n", 1)[1].splitlines()
    script = []
    for line in lines:
        if line.strip() and not line.startswith("          "):
            break
        script.append(line[10:])
    return "\n".join(script) + "\n"


def write_index(repo: Path) -> None:
    """The caller's script without `--check`: the index written from the records."""
    subprocess.run([sys.executable, "-I", str(repo / SCRIPT)], check=True)


def check(tmp_path: Path) -> tuple[int, str]:
    """Run the index step in the caller's checkout `tmp_path/caller`: exit code and output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    python3 = bin_dir / "python3"
    python3.write_text(PYTHON3)
    python3.chmod(python3.stat().st_mode | stat.S_IXUSR)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PYTHON": sys.executable,
        "GITHUB_WORKSPACE": str(tmp_path / "caller"),
    }
    done = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step("index")],
        cwd=tmp_path / "caller",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def errors(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("::error::")]


@pytest.fixture
def caller(tmp_path: Path) -> Path:
    """A caller's checkout: two records, its script and the index the script wrote."""
    repo = tmp_path / "caller"
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "adr" / "0001-one-form-of-title.md").write_text("# ADR-0001: One form\n")
    (repo / "docs" / "adr" / "0002-a-cap.md").write_text("# ADR-0002: A cap\n")
    (repo / "scripts").mkdir()
    (repo / SCRIPT).write_text(STAND_IN)
    write_index(repo)
    return repo


def test_the_check_runs_as_a_called_job_only() -> None:
    triggers = workflow().split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_call:" in triggers
    assert "pull_request" not in triggers
    assert "push" not in triggers
    assert "secrets:" not in triggers
    assert "\npermissions:\n  contents: read\n" in workflow()
    assert "write" not in workflow().split("\npermissions:", 1)[1].split("\njobs:", 1)[0]


def test_the_job_is_named_for_its_check_and_times_out() -> None:
    assert "\njobs:\n  adr-index:\n    name: adr-index\n" in workflow()
    assert "    timeout-minutes: 5\n" in workflow()


def test_actions_are_pinned_to_commits_and_the_checkout_keeps_no_token() -> None:
    steps = "\n".join(line for line in workflow().splitlines() if not line.startswith("#"))
    uses = re.findall(r"uses: (\S+)( # v[\d.]+)?", steps)
    assert uses
    for ref, version in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
        assert version, ref
    assert "persist-credentials: false" in workflow()


def test_the_checkout_is_the_one_spelling_pins() -> None:
    spelling = (WORKFLOWS / "spelling.yml").read_text()
    pinned = re.findall(r"uses: (actions/checkout@\S+ # v[\d.]+)", spelling)
    assert pinned
    assert re.findall(r"uses: (actions/checkout@\S+ # v[\d.]+)", workflow()) == pinned


def test_the_workflow_runs_the_callers_own_script() -> None:
    script = step("index")
    assert f"script={SCRIPT}\n" in script
    assert 'python3 -I "$script" --check' in script
    # the caller's checkout alone, and no copy of the script here
    assert "repository:" not in workflow()
    assert not (ROOT / SCRIPT).exists()


def test_a_current_index_passes(tmp_path: Path, caller: Path) -> None:
    code, out = check(tmp_path)
    assert code == 0, out
    assert not errors(out), out


def test_a_record_without_its_index_fails_and_names_the_script(
    tmp_path: Path, caller: Path
) -> None:
    (caller / "docs" / "adr" / "0003-a-third.md").write_text("# ADR-0003: A third\n")
    before = {name: (caller / name).read_text() for name in ("docs/adr.md", "docs/adr.json")}
    code, out = check(tmp_path)
    assert code != 0, out
    assert any(f"`{RUN}`" in line for line in errors(out)), out
    # the check writes nothing
    assert {name: (caller / name).read_text() for name in before} == before
    write_index(caller)
    code, out = check(tmp_path)
    assert code == 0, out


@pytest.mark.parametrize("name", ["docs/adr.md", "docs/adr.json"])
def test_an_index_edited_by_hand_fails(tmp_path: Path, caller: Path, name: str) -> None:
    path = caller / name
    if name.endswith(".json"):
        path.write_text(json.dumps({"records": ["0001-one-form-of-title.md"]}) + "\n")
    else:
        path.write_text(path.read_text() + "- 0003-a-third.md\n")
    code, out = check(tmp_path)
    assert code != 0, out
    assert any(f"`{RUN}`" in line for line in errors(out)), out


def test_a_missing_index_fails(tmp_path: Path, caller: Path) -> None:
    (caller / "docs" / "adr.json").unlink()
    code, out = check(tmp_path)
    assert code != 0, out
    assert any(f"`{RUN}`" in line for line in errors(out)), out


def test_a_record_that_does_not_read_is_mended_before_the_script_runs(
    tmp_path: Path, caller: Path
) -> None:
    """The script writes nothing while a record does not read, so running it alone mends nothing:
    the annotation says first to mend what the script's lines name (.github#59, finding 1)."""
    (caller / "docs" / "adr" / "0003-wrong.md").write_text("# Wrong title\n")
    code, out = check(tmp_path)
    assert code != 0, out
    assert "docs/adr/0003-wrong.md: the first line does not read" in out
    failed = [line for line in errors(out) if f"`{RUN}`" in line]
    assert len(failed) == 1, out
    assert "mend" in failed[0], out
    assert failed[0].index("mend") < failed[0].index(f"`{RUN}`"), out


def test_a_number_taken_twice_fails_whatever_the_script_says(tmp_path: Path, caller: Path) -> None:
    (caller / "docs" / "adr" / "0002-another-cap.md").write_text("# ADR-0002: Another cap\n")
    write_index(caller)
    code, out = check(tmp_path)
    assert code != 0, out
    twice = [line for line in errors(out) if "ADR-0002" in line]
    assert len(twice) == 1, out
    assert "docs/adr/0002-a-cap.md" in twice[0]
    assert "docs/adr/0002-another-cap.md" in twice[0]
    assert f"`{RUN}`" in twice[0]


def test_only_a_numbered_record_takes_a_number(tmp_path: Path, caller: Path) -> None:
    (caller / "docs" / "adr" / "0002.md").write_text("A file without a slug.\n")
    (caller / "docs" / "adr" / "0002-draft.txt").write_text("Not a record.\n")
    write_index(caller)
    code, out = check(tmp_path)
    assert code == 0, out


def test_a_record_name_cannot_start_a_workflow_command(tmp_path: Path, caller: Path) -> None:
    (caller / "docs" / "adr" / "0002-x\n::warning::planted 100%.md").write_text(
        "# ADR-0002: Planted\n"
    )
    write_index(caller)
    code, out = check(tmp_path)
    assert code != 0, out
    assert not any(line.startswith("::warning::") for line in out.splitlines()), out
    twice = [line for line in errors(out) if "ADR-0002" in line]
    assert len(twice) == 1, out
    assert "0002-x%0A::warning::planted 100%25.md" in twice[0]


def test_a_caller_without_the_script_fails_and_names_it(tmp_path: Path, caller: Path) -> None:
    (caller / SCRIPT).unlink()
    code, out = check(tmp_path)
    assert code != 0, out
    assert any(SCRIPT in line for line in errors(out)), out


def test_the_readme_shows_the_workflow_and_its_caller() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "**`.github/workflows/adr-index.yml`**" in readme
    assert "uses: xippios/.github/.github/workflows/adr-index.yml@main" in readme
    assert "`adr-index / adr-index`" in readme
