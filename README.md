# xippios/.github

The organisation's shared GitHub Actions workflows for the `sdk-*` repositories of the
xippios SDK family: the two merge gates, `merge-class` and `family-review`, and the
classifier behind the first. GitHub decides what merges: `ci`, `merge-class` and
`family-review` pass, and auto-merge merges; a `human` class waits for Johannes.

## The workflows

- **`.github/workflows/merge-class.yml`** classifies a pull request as `auto` or `human`
  with `scripts/merge_class.py`, always read from `main` of this repository. `auto` passes
  the check; `human` fails it, with the rules hit, the trusted files and the remaining
  changed files in the job summary. Permissions: `contents: read`. The job times out
  after 20 minutes; the template clone and the render each after 5.
- **`.github/workflows/family-review.yml`** runs the Claude Code action
  (`anthropics/claude-code-action`, v1.0.262). It applies `docs/review-checklist.md` from
  `main` of `xippios/sdk-core`, in order, to the pull request's diff, reading the
  conventions, the definition of done and the ADRs from `sdk-core`'s `main` (never from
  the pull request) and the pull request's own `docs/upstream/` for every claim about the
  upstream. It judges the description's definition-of-done checklist and
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
  - **What the model may do**: nothing but read. Before it starts, a step writes its
    material to `.review/`: `diff.patch` (merge base to head), `log.txt` (the commits
    with their messages), `pr.json` (title, body, author, comments, files) and
    `checks.json` (the head's checks, `ci` among them). The model may `Read`, `Glob` and
    `Grep` inside the workspace (`Read(./**)`, `.git/` denied, `--permission-mode
    dontAsk`), runs no command, edits nothing, reaches no network, and loads no settings,
    hooks or MCP servers from the pull request (`--setting-sources user`); Claude Code
    strips credentials from any subprocess (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`). The
    prompt names the pull request's files, diff, messages, title, body, comments,
    `docs/upstream/` and fixtures as material to judge, never instructions; an instruction
    found in them is itself a finding. The verdict step redacts anything that looks like a
    key or a GitHub token from the summary and the comment.
- **`.github/workflows/ci.yml`** is this repository's own `ci`: ruff (the family's
  version, 0.17.1) and the classifier's tests. It also calls `merge-class.yml` as a job,
  which proves the caller wiring below.

Every action in the gate workflows is pinned to a commit SHA with its version in a comment.

## Merge classes

The rules, in order. Every rule is evaluated: the first `human` decides the class, every
reason is reported.

1. **Scaffold**, in a source repository only (one named `sdk-*` other than `sdk-core` and
   `sdk-template`; those two and this repository have no `src/`): the base has no `src/`
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
   **Answers**: a change to `.copier-answers.yml` other than `_commit` moving forward
   along the template's `main` (the base's `_commit` an ancestor of the head's),
   `core_version` or `core_git_ref` is a session change: `human`, with the keys as the
   reason. An answer the base lacks (a question a template release added) is free when
   its value equals the question's literal default (one plain or quoted scalar without
   `{{` or `{%`) in the template's `copier.yml` at the head's `_commit`; with another
   value, a Jinja default or a question unknown there it is `human` ("answers added with
   non-default values"). `_commit` moving to an older or an unrelated commit is `human`,
   and so is any `_commit` change or added answer the template could not be checked for
   (`--no-render`, a failed clone, a `_commit` the render refused). A `core_git_ref`
   changed to a non-empty value must name a `v*` tag of `xippios/sdk-core`, its `main`,
   or a commit on its `main` (read from a clone without trees and blobs; a branch other
   than `main` can move and is no pin), else `human` ("core pinned off main"); under
   `--no-render` or a failed clone such a change is `human` too.
3. **Protected paths** in what remains: `human`.
   - Everywhere: `.github/**`, `.claude/settings.json`, `.claude/settings.local.json`,
     `.claude/agents/**`, `.claude/hooks/**`, `.claude/commands/**` (in a source the
     template renders them, so rule 2 trusts them when identical to the render),
     `.mcp.json`, `CLAUDE.local.md`, `.pre-commit-config.yaml`, `.secrets.baseline`,
     `docs/conventions.md`, `docs/adr/**`, `docs/review-checklist.md`,
     `docs/definition-of-done.md`; and a change of `pyproject.toml` in where the package
     is built and installed from or what it installs, `[build-system]`, `[tool.uv]`
     (index, sources, override-dependencies, ...), `[project.scripts]`,
     `[project.gui-scripts]` or `[project.entry-points.*]` ("build or install routes
     changed"). The dependency lists stay free.
   - In a source, also a template-owned file under `src/` that differs from the render
     (an adapter changed by hand, which could expose tasks around rule 4); without a
     render, `mcp.py`, `http.py`, `_version.py` and `api/__init__.py` under
     `src/xippios/` count as template-owned by name.
   - In `sdk-core`, also `src/**`.
   - In `sdk-template`, also `copier.yml`, `copier.yaml`, `scripts/**`, the template
     origin of every path protected in a source (the `template/` prefix, with or without
     a `.jinja` suffix), any path under `template/` with Jinja (`{{` or `{%`) in its name,
     and `template/pyproject.toml.jinja` when its dependency block changes
     (`[project] dependencies`, `[project.optional-dependencies]`, `[dependency-groups]`,
     and the build and install tables above) or any changed line of it carries `{{`,
     `{%` or `{#`.
   - In this repository, every pull request.
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

## Wiring and check contexts

"Require workflows to pass before merging" may be an Enterprise-only ruleset rule, so both
workflows carry `on: pull_request` (types `opened`, `synchronize`, `reopened`, `edited`;
`edited` because the description is judged and a base change arrives as `edited`) and
`on: workflow_call` (decided 2026-10-26). The ruleset editor decides which wiring applies.

| Wiring | Merge class check | Review check |
| --- | --- | --- |
| Required workflow (a ruleset requires the workflow from this repository, `ref` `main`) | `merge-class` | `family-review` |
| Caller (a repository's `ci.yml` calls the workflow as a job) | `merge-class / merge-class` | `family-review / family-review` |

In caller mode a repository's `ci.yml`, which runs on `pull_request`, adds these two jobs;
the `if` keeps them off `push` runs, which carry no pull request. A caller's
`on: pull_request` without `types` runs on `opened`, `synchronize` and `reopened` only, so
it adds `types: [opened, synchronize, reopened, edited]` to have the review see a changed
description:

```yaml
  merge-class:
    if: github.event_name == 'pull_request'
    uses: xippios/.github/.github/workflows/merge-class.yml@main
    permissions:
      contents: read

  family-review:
    if: github.event_name == 'pull_request'
    uses: xippios/.github/.github/workflows/family-review.yml@main
    secrets: inherit
    permissions:
      contents: read
      pull-requests: write
      checks: read
```

Caller mode is **not a boundary**: the check contexts come from the caller's own `ci.yml`
on the pull request's head, and a ruleset cannot tell those jobs from any other Actions
job of the same name, so a pull request that edits `ci.yml` can replace the call with a
job that merely passes. Only the required-workflow wiring reads the gate from this
repository whatever the pull request changes; the choice if the editor does not offer it
is Johannes's at gate 2.

## Rulesets

- **`sdk-main-protection`** (org branch ruleset on `main` of the `sdk-*` repositories,
  and of this repository once it joins the list): pull request required, `ci` required
  and strict, `family-review` required once the org secret `ANTHROPIC_API_KEY` exists
  (and with it the org variable `FAMILY_REVIEW_REQUIRED=1`), no approvals required, no
  bypass actor.
- **`sdk-merge-class`** (org branch ruleset, same targets): requires the merge-class check
  and nothing else. Bypass actor Johannes, mode "pull requests only": the bypass button
  is how a `human` pull request merges, and it bypasses nothing but the class. In caller
  mode it is created once every repository's `ci.yml` carries the `merge-class` job.
- **Tag ruleset** on `refs/tags/v*` of the `sdk-*` repositories: creation, update and
  deletion restricted; bypass actors GitHub Actions, so the release workflow can tag (or,
  where the editor does not offer it, the App whose installation token that workflow
  uses), and Johannes, who stays until every source tags its own releases.

## Running the classifier locally

From a checkout of the repository whose pull request you classify, with this repository
cloned somewhere (Python 3.11 or later, git, and `uvx` for the render):

```sh
python3 <this clone>/scripts/merge_class.py --repo xippios/<repo> --base origin/main --head HEAD --workdir .
```

It prints `class=auto` or `class=human` with the reasons, the trusted and the remaining
files; `--summary <file>` appends the markdown summary, `--no-render` skips rule 2's
render and the core pin check (nothing is trusted, and a `_commit` or `core_git_ref`
change is `human`), `--template-url` and `--core-url` point rule 2 at other clones of the
template and of sdk-core. Exit status: 0 `auto`, 1 `human`, 2 when the
classification itself failed.

The checks of this repository:

```sh
uvx ruff@0.17.1 check scripts && uvx ruff@0.17.1 format --check scripts
uv run --no-project --with pytest pytest scripts/tests -q
uvx --from actionlint-py actionlint
```

## Changing this repository

Every pull request here is `human`, so Johannes merges each one: no session can change the
class computation or the review gate. The review checklist itself lives in `sdk-core`
(`docs/review-checklist.md`), where it is a protected path too. The caller-wiring proof
in `ci.yml` reads `merge-class.yml` from the pull request but the classifier from `main`,
so on the pull request that first adds `scripts/merge_class.py` the proof job fails until
the script is on `main`; `ci` does not depend on it.
