# xippios/sdk-gates

The organisation's shared GitHub Actions workflows for the `sdk-*` repositories of the
xippios SDK family: the two merge gates, `merge-class` and `family-review`, and the
classifier behind the first. GitHub decides what merges: `ci`, `merge-class` and
`family-review` pass, and auto-merge merges; a `human` class waits for Johannes.

Renamed from `xippios/.github` on 2026-10-27. GitHub does not redirect `uses:` references
to the old name, so every caller names `sdk-gates` (sdk-core since #26, sdk-template
since v0.2.2).

## The workflows

- **`.github/workflows/merge-class.yml`** classifies a pull request as `auto` or `human`
  with `scripts/merge_class.py`, always read from `main` of this repository. `auto` passes
  the check; `human` fails it, with the rules hit, the trusted files and the remaining
  changed files in the job summary. Permissions: `contents: read`. The job times out
  after 20 minutes; the template clone, the render and the sdk-core clone each after 5.
- **`.github/workflows/family-review.yml`** runs the Claude Code action
  (`anthropics/claude-code-action`, v1.0.262). It applies `docs/review-checklist.md` from
  `main` of `xippios/sdk-core`, in order, to the pull request's diff, reading the
  conventions, the definition of done and the ADRs from `sdk-core`'s `main` (never from
  the pull request) and the pull request's own `docs/upstream/` for every claim about the
  upstream. One exception: when an `sdk-core` pull request changes the checklist, the
  conventions, the definition of done or an ADR, the review reads its branch's version
  of exactly those documents, since for the documents a pull request itself changes the
  branch's version applies; such a pull request is class `human`, and Johannes reads the
  change. Without the checklist, the conventions or the definition of done the review
  fails closed. It judges the description's definition-of-done checklist and
  `Decisions taken` block and returns a JSON verdict, `ready` or `not ready`, with
  findings. `ready` passes; `not ready` fails the check and puts the findings in one
  sticky PR comment, which a later `ready` updates. Permissions: `contents: read`,
  `pull-requests: write`, `checks: read`.
  - **Identity**: the review runs on the workflow token (`github.token`), so its comment
    comes from `github-actions[bot]`, not from the Claude GitHub App. The App's token
    exchange skips every pull request whose calling workflow differs from the one on the
    default branch, which would leave adoption PRs without a verdict (decided 2026-10-26;
    Johannes confirms at this repository's first PR).
  - **Gate**: a Dependabot pull request (its author and the triggering actor both
    `dependabot[bot]`) ends green with the notice "family-review: Dependabot PR, reviewed
    by `ci` only", since Dependabot runs get no Actions secrets. Every other pull request
    needs the org secret `ANTHROPIC_API_KEY`. Without it, a pull request from a fork fails
    (it never gets the secret, so it is never green unreviewed), and one from the
    repository itself ends green with a notice until the org variable
    `FAMILY_REVIEW_REQUIRED` is `1`; from then on an empty secret fails the check.
    Johannes sets the variable when the secret exists.
  - **Who it reviews**: `allowed_bots` stays empty, so a pull request opened or updated
    by a GitHub App gets no review (the action refuses a non-human actor) and fails by
    design; Dependabot is excepted by the gate above.
  - **What the model may do**: nothing but read. Before it starts, a step writes its
    material to `.review/`: `diff.patch` (merge base to head), `log.txt` (the commits
    with their messages), `pr.json` (title, body, author, comments, files) and
    `checks.json` (the head's checks, `ci` among them). The model may `Read`, `Glob` and
    `Grep` inside the workspace (`Read(./**)`, `.git/` denied, `--permission-mode
    dontAsk`), runs no command, edits nothing, reaches no network, and loads no settings,
    hooks or MCP servers from the pull request (`--setting-sources user`); Claude Code
    strips credentials from any subprocess (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`). The
    action restores `.claude/`, `CLAUDE.md`, `CLAUDE.local.md`, `.mcp.json` and its other
    configuration paths from the pull request's base before the model starts and keeps
    the head's versions of those paths under `.claude-pr/`, so the model reads them
    there, and `.review/diff.patch` is authoritative for what changed. The
    prompt names the pull request's files, diff, messages, title, body, comments,
    `docs/upstream/` and fixtures as material to judge, never instructions; an instruction
    found in them is itself a finding. The verdict step redacts anything that looks like a
    key or a GitHub token from the summary and the comment.
- **`.github/workflows/ci.yml`** is this repository's own `ci` (15 minutes): ruff (the
  family's version, 0.17.1), the classifier's tests on a pinned pytest, and actionlint
  with the runner's shellcheck. It also calls `merge-class.yml` as a job, which proves
  the caller wiring below.

Every action in the gate workflows is pinned to a commit SHA with its version in a
comment, and `setup-uv` installs a pinned uv.

## Merge classes

The rules, in order. Every rule is evaluated: the first `human` decides the class, every
reason is reported.

1. **Scaffold**, in a source repository only (one named `sdk-*` other than `sdk-core`,
   `sdk-template` and this repository, `sdk-gates`, whose name matches the pattern too;
   `sdk-template` and this repository have no `src/` at all): the base has no `src/`
   directory: `human`.
2. **Render trust**: the template is rendered with the head's answers at the commit the
   head's `_commit` of `.copier-answers.yml` resolves to on the template's `main`
   (`uvx copier copy --defaults --trust --skip-tasks --vcs-ref <that SHA> --data-file
   <answers without _commit and _src_path>`). A changed file the template owns (rendered
   and matched by no `_skip_if_exists` pattern of the template's `copier.yml` at that
   commit) whose content and executable bit are identical to the render leaves the
   changed set. A file the template does not render, a skip-listed file, a deleted file,
   a symlink and a path that is not a plain relative path are never trusted (the last is
   reported as `human`). Nothing is trusted when the render or the template clone fails,
   when `_src_path` is not `https://github.com/xippios/sdk-template.git`, when `_commit`
   is not a plain git ref, or when it is not on the template's `main`.
   **Answers file**: the head's `.copier-answers.yml` is read only inside a subset of
   YAML: every line at column 0 blank, a `#` comment or `key: value` with an unquoted
   plain key, no top-level key twice, and no continuation line under `_commit`,
   `core_version` or `core_git_ref`. Outside it the pull request is `human` and nothing
   is trusted, since YAML, and so copier, may read a key or a value the classifier does
   not see (a quoted key, the later of two duplicates). When the answers file changed, or
   when rule 2 trusts any file, it must also be byte-identical to the `.copier-answers.yml`
   copier writes back in the render, `_commit` and `_src_path` as copier writes them;
   otherwise the pull request is `human` ("answers file is not in copier's canonical
   form") and nothing is trusted. A changed answers file no render could check
   (`--no-render`, a failed clone or render) is `human` as well.
   **Answers**: in that form, a changed answer other than `_commit` moving forward along
   the template's `main` (the base's `_commit` an ancestor of the head's), `core_version`
   or `core_git_ref` is a session change: `human`, with the keys as the reason. An answer
   the base lacks (a question a template release added) is free when its value equals the
   question's literal default (one plain or quoted scalar without `{{`, `{%` or `{#`) in
   the template's `copier.yml` at the head's `_commit`; with another value, a Jinja
   default or a question unknown there it is `human` ("answers added with non-default
   values"). A key the base has and the head lacks is free when the template at the
   head's `_commit` no longer asks it (a question a template release removed, whose
   answer `copier update` drops); while that `copier.yml` has a question of its name,
   whatever its `when:` or `ask:`, it is `human` ("answers dropped by hand"). `_commit`
   moving to an older or an unrelated commit is `human`, and so is a `_commit` change or
   an added or dropped answer the template could not be checked for (`--no-render`, a
   failed clone, a `_commit` the render refused).
   **Core pin**: a non-empty `core_git_ref` on the head is accepted in two forms only:
   `main`, which uv reads as the branch of `xippios/sdk-core` before any tag or commit, and
   a full SHA (40 lowercase hex characters) of a commit on sdk-core's `main` (read from a
   clone without trees and blobs). uv takes a full SHA as the commit itself, so no branch
   or hex-named tag can take it over. Every other form (a `v*` tag, a short hex, a branch
   name, `refs/...`) is `human` ("core pinned off main or not a full SHA") without a
   lookup: each names a ref that can move, or one that a branch created later by its name
   would take over at the next `uv lock`, since uv reads a branch first. The pin is
   checked whether or not the pull request changes it, so every pull request is `human`
   while core is pinned off `main` or by another form; when sdk-core cannot be cloned to
   check a full SHA it is `human` too, and under `--no-render` a change to a non-empty
   value is.
3. **Protected paths** in what remains: `human`.
   - Everywhere: `.github/**`, `.claude/settings.json`, `.claude/settings.local.json`,
     `.claude/agents/**`, `.claude/hooks/**`, `.claude/commands/**` (in a source the
     template renders them, so rule 2 trusts them when identical to the render),
     `.mcp.json`, `CLAUDE.local.md`, `.pre-commit-config.yaml`, `.secrets.baseline`,
     `hatch.toml` (hatchling merges a root `hatch.toml` over `[tool.hatch]`), `uv.toml`
     (uv reads a root `uv.toml` as it reads `[tool.uv]`, and ignores `[tool.uv]` when both
     exist), `docs/conventions.md`, `docs/adr/**`, `docs/review-checklist.md`,
     `docs/definition-of-done.md`; and a change in `pyproject.toml` to where the package
     is built and installed from or to what it installs: `[build-system]`, `[tool.uv]`
     (index, sources, override-dependencies, ...), the whole `[tool.hatch]` (the packaged
     paths, targets and build hooks under `[tool.hatch.build]`, the metadata hooks under
     `[tool.hatch.metadata]`, the version source `[tool.hatch.version]`: code that runs at
     build time), `[project.scripts]`, `[project.gui-scripts]` or
     `[project.entry-points.*]` ("build or install routes changed"). The dependency lists
     stay free. `.github/**` protects the workflow definitions, not the code a workflow
     runs with a secret: the tests and scripts that `live.yml` runs with a key can merge
     `auto`, and the family review reads them.
   - In a source, also a template-owned file under `src/` that differs from the render
     (an adapter changed by hand, which could expose tasks around rule 4); without a
     render, `mcp.py`, `http.py`, `_version.py` and `api/__init__.py` under
     `src/xippios/` count as template-owned by name.
   - In a source, also `tests/test_family.py` and `tests/conftest.py`, the template-owned
     test files that carry the family conformance check and the plugin line that serves
     it: changed and not identical to the render ("a template-owned test file changed by
     hand"), or deleted, whatever the render says, since rule 2 trusts no deleted file.
     Without a render (no answers file, `--no-render`, a failed render) both count as
     template-owned by name. `tests/test_tasks.py` is the session's (skip-listed) and
     stays free.
   - In `sdk-core`, also `src/**`.
   - In `sdk-template`, also `copier.yml`, `copier.yaml`, `scripts/**`, the template
     origin of every path protected in a source (the `template/` prefix, with or without
     a `.jinja` suffix: `template/hatch.toml`, `template/uv.toml` and their `.jinja`
     forms among them), any path under `template/` with Jinja (`{{` or `{%`) in its name,
     and `template/pyproject.toml.jinja` when its dependency block changes
     (`[project] dependencies`, `[project.optional-dependencies]`, `[dependency-groups]`,
     and the build and install tables above), read past Jinja, `#` comments and strings
     (basic, literal and multi-line), so a bracket in a comment or a string opens nothing,
     and with headers and keys read as TOML spells them (bare and quoted parts, anything
     inside the quotes, spaces and tabs around the dots and the name), a header or key
     with a backslash in it refused outright as protected, whatever it names, since a
     basic-string escape (`"\u0075v"`) can spell any name; when it ends inside a
     multi-line string or a Jinja tag; when any changed line of it carries `{{`, `{%` or
     `{#`; and, as a second net should that reading go wrong, when any changed line of
     it, read on its own at any depth, looks like a header or a key of `[tool.uv]`,
     `[build-system]`, `[tool.hatch]`, `[project.scripts]`, `[project.gui-scripts]`,
     `[project.entry-points]`, `[dependency-groups]` or `[project.optional-dependencies]`
     (`[tool.uv]`, `tool.uv.index-url = ...`, `uv.index-url = ...` under `[tool]`).
   - In this repository, `sdk-gates`, every pull request.
4. **First surface**: a `src/xippios/**/tasks.py` whose `__all__` was empty or absent
   names at least one task: `human`. An `__all__` that cannot be read statically is
   `human` too: anything but top-level assignments of a literal list or tuple of strings
   (and `+=` of one), any other mention of `__all__` (an import of or as it, a method
   call, a def, a loop, a read that could alias it), a star import, a module
   `__getattr__`, an `"__all__"` string (`globals()["__all__"]`,
   `setattr(sys.modules[...], "__all__", ...)`), `globals`, `vars`, `locals`, `setattr`,
   `exec`, `eval`, `__import__`, `sys.modules` or `__dict__`. That static reading has
   limits (an adapter, a module the tasks import, a name bound at run time), so in a
   source whose base exports no task from any `tasks.py` (empty, absent or unreadable
   `__all__`), every changed file under `src/` that remains after rule 2 is `human` too:
   the bootstrap closes them until the first surface has merged.
5. **Release**: when the `[project]` version of `pyproject.toml` changes, what remains
   must be a subset of `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, `README.md`,
   `CLAUDE.md`, `docs/handover.md` and `scripts/check-siblings.sh`; else `human`.
6. Otherwise **`auto`**.

The changed set and the comparisons of rules 2 to 5 are taken against the merge base of
base and head, which is the base itself once the pull request is up to date with its
branch (the required checks are strict). The branch name is no input. The classifier
reads the pull request as git objects and executes nothing from it; file names and
answers are escaped in the summary and the report.

## Known limits

- `template/pyproject.toml.jinja` is judged by a text scan, since a Jinja template is not
  TOML. Its structural replacement, rendering the template at base and head and comparing
  the protected tables with a TOML parser, is a follow-up.
- The core pin check accepts only `main` and a full SHA, the two forms no ref created
  later can take over in uv's reading. A tag or a short commit name read anywhere else
  (by a human, by a tool) can still be shadowed by a branch created later; the classifier
  cannot see that, so it rests on the rulesets below: the `v*` tag ruleset of every
  `sdk-*` repository and the branch ruleset on sdk-core that forbids `v*` and hex-like
  branch names.

## Wiring and check contexts

"Require workflows to pass before merging" may be an Enterprise-only ruleset rule, so both
workflows carry `on: pull_request` (types `opened`, `synchronize`, `reopened`, `edited`;
`edited` because the description is judged and a base change arrives as `edited`) and
`on: workflow_call` (decided 2026-10-26). The ruleset editor decides which wiring applies.

| Wiring | Merge class check | Review check |
| --- | --- | --- |
| Required workflow (a ruleset requires the workflow from this repository, `ref` `main`) | `merge-class` | `family-review` |
| Caller (a repository's `gates.yml` calls the workflow as a job) | `merge-class / merge-class` | `family-review / family-review` |

A skipped caller job reports one check named after the caller job alone (`merge-class`,
`family-review`), never the slash-joined context, and GitHub counts a skipped check as
passing. So a ruleset must never require the bare names: while `GATES_CALLER` is unset, a
switched-off `gates.yml` would satisfy both. In caller mode a ruleset requires the
slash-joined contexts, and only once the variable is set in every repository the ruleset
targets; requiring them earlier leaves every pull request pending. The required-workflow
rule has no such gap.

In caller mode a repository carries its own caller file, `.github/workflows/gates.yml`,
beside `ci.yml`. It runs on `pull_request` with
`types: [opened, synchronize, reopened, edited]`: a caller's `on: pull_request` without
`types` runs on the first three only, and `edited` matters to both gates, to the review
because the description is judged and to `merge-class` because a change of the base
branch arrives as `edited`. The caller can ship before the ruleset decision: both jobs
carry `if: vars.GATES_CALLER == '1'` and run only once Johannes sets that repository
variable, which he does per repository if the editor does not offer the required-workflow
rule. It passes the review exactly one secret, never `secrets: inherit`:

```yaml
name: gates

on:
  pull_request:
    types: [opened, synchronize, reopened, edited]

permissions:
  contents: read

jobs:
  merge-class:
    if: vars.GATES_CALLER == '1'
    uses: xippios/sdk-gates/.github/workflows/merge-class.yml@main
    permissions:
      contents: read

  family-review:
    if: vars.GATES_CALLER == '1'
    uses: xippios/sdk-gates/.github/workflows/family-review.yml@main
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    permissions:
      contents: read
      pull-requests: write
      checks: read
```

Caller mode is **not a boundary**: the check contexts come from the caller's own
`gates.yml` on the pull request's head, and a ruleset cannot tell those jobs from any
other Actions job of the same name, so a pull request that edits `gates.yml` can replace
the call with a job that merely passes. Only the required-workflow wiring reads the gate
from this repository whatever the pull request changes; the choice if the editor does not
offer it is Johannes's at gate 2.

## Rulesets

- **`sdk-main-protection`** (org branch ruleset on `main` of the `sdk-*` repositories,
  this one among them by its name since the rename): pull request required, `ci` required
  and strict, `family-review` required once the org secret `ANTHROPIC_API_KEY` exists (by the
  required-workflow rule, or the slash-joined context `family-review / family-review` in caller
  mode, never the bare name)
  (and with it the org variable `FAMILY_REVIEW_REQUIRED=1`), no approvals required, no
  bypass actor.
- **`sdk-merge-class`** (org branch ruleset, same targets): requires the merge-class check (the
  required-workflow rule, or the slash-joined context `merge-class / merge-class` in caller mode
  once `GATES_CALLER` is set in every target, never the bare name)
  and nothing else. Bypass actor Johannes, mode "pull requests only": the bypass button
  is how a `human` pull request merges, and it bypasses nothing but the class. In caller
  mode it is created once every repository carries `gates.yml`.
- **Tag ruleset** on `refs/tags/v*`, one for every `sdk-*` repository, sdk-core
  included: creation, update and deletion restricted; the only bypass actors, so the
  only creators of `v*` tags, are GitHub Actions, for the release workflow (or, where the
  editor does not offer it, the App whose installation token that workflow uses), and
  Johannes. sdk-core tags its own releases from 0.2.1 like every repository.
- **Branch ruleset on sdk-core**: forbids branch names matching `v*` and hex-like names,
  so a branch created later cannot shadow a tag or a short commit name.

## Running the classifier locally

From a checkout of the repository whose pull request you classify, with this repository
cloned somewhere (Python 3.11 or later, git, and `uvx` for the render):

```sh
python3 <this clone>/scripts/merge_class.py --repo xippios/<repo> --base origin/main --head HEAD --workdir .
```

It prints `class=auto` or `class=human` with the reasons, the trusted and the remaining
files; `--summary <file>` appends the markdown summary, `--no-render` skips rule 2's
render and the core pin check (nothing is trusted, and any change to
`.copier-answers.yml` is `human`), `--template-url` and `--core-url` point rule 2 at other
clones of the template and of sdk-core. Exit status: 0 `auto`, 1 `human`, 2 when the
classification itself failed.

The checks of this repository:

```sh
uvx ruff@0.17.1 check scripts && uvx ruff@0.17.1 format --check scripts
uv run --no-project --with pytest==9.1.1 pytest scripts/tests -q
uvx --from actionlint-py==1.7.12.25 actionlint
```

`ci` runs actionlint with the runner's shellcheck; locally, add it with
`uvx --from actionlint-py==1.7.12.25 --with shellcheck-py sh -c actionlint`.

## Changing this repository

Every pull request here is `human`, so Johannes merges each one: no session can change the
class computation or the review gate. The review checklist itself lives in `sdk-core`
(`docs/review-checklist.md`), where it is a protected path too. The caller-wiring proof
in `ci.yml` reads `merge-class.yml` from the pull request but the classifier from `main`,
so on the pull request that first adds `scripts/merge_class.py` the proof job fails until
the script is on `main`; `ci` does not depend on it.
