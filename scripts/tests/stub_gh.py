"""A stub `gh` for the job `range` of `conventions-range.yml` (step 3.1 of .github 0.5.0): it logs
each call and answers from `answers.json` beside it. `pr view` prints the pull request's title and
labels (`view`); `api` on a comments endpoint prints the page that `page=` asks for (`comments`,
one list per page), on a `contents` endpoint the document (`document`); `api --method` keeps what
it was given on its standard input in `written`, a line per call. An answer the test gave as
`None` fails the call, and `write_fails` fails every write with an error that carries a
token-shaped text."""

import json
import sys
from pathlib import Path

STUB = """\
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
args = sys.argv[1:]
with (HERE / "calls").open("a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
answers = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))
if args[:2] == ["pr", "view"]:
    if answers.get("view") is None:
        sys.exit("gh: Server Error (HTTP 502)")
    print(json.dumps(answers["view"]))
    sys.exit(0)
if args[:1] != ["api"]:
    sys.exit("stub: no call it knows")
endpoint = next(arg for arg in args if arg.startswith("repos/"))
if "--method" in args:
    method = args[args.index("--method") + 1]
    given = json.loads(sys.stdin.read())
    with (HERE / "written").open("a", encoding="utf-8") as out:
        out.write(json.dumps({"method": method, "endpoint": endpoint, "input": given}) + "\\n")
    if answers.get("write_fails"):
        token = "ghs_" + "abc123"
        sys.exit(f"HTTP 403: Resource not accessible by integration ({token})")
    print("{}")
    sys.exit(0)
if "/contents/" in endpoint:
    print(answers.get("document", "# a document\\n"), end="")
    sys.exit(0)
pages = answers.get("comments")
if pages is None:
    sys.exit("gh: Server Error (HTTP 502)")
page = int(endpoint.rsplit("page=", 1)[1])
print(json.dumps(pages[page - 1] if page <= len(pages) else []))
"""


def install(bin_dir: Path, answers: dict) -> Path:
    """Write the stub and its answers into `bin_dir`, emptied of the calls of a run before."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "answers.json").write_text(json.dumps(answers))
    for name in ("calls", "written"):
        (bin_dir / name).unlink(missing_ok=True)
    (bin_dir / "stub.py").write_text(STUB)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "$(dirname "$0")/stub.py" "$@"\n')
    gh.chmod(0o755)
    return bin_dir


def calls(bin_dir: Path) -> list[list[str]]:
    """The calls the stub logged, each its arguments."""
    log = bin_dir / "calls"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def written(bin_dir: Path) -> list[dict]:
    """The writes the stub was given: each its method, its endpoint and its input."""
    log = bin_dir / "written"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def comment(number: int, body: str, login: str = "github-actions[bot]") -> dict:
    """A comment of a pull request as the REST API lists it."""
    return {"id": number, "user": {"login": login}, "body": body}
