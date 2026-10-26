# xippios/.github

The organisation's shared GitHub Actions workflows for the `sdk-*` repositories of the
xippios SDK family: the two merge gates, `merge-class` and `family-review`, and the
classifier behind the first. GitHub decides what merges: `ci`, `merge-class` and
`family-review` pass, and auto-merge merges; a `human` class waits for Johannes.

## The workflows

- **`.github/workflows/merge-class.yml`** classifies a pull request as `auto` or `human`
  with `scripts/merge_class.py`, always read from `main` of this repository. `auto` passes
  the check; `human` fails it, with the rules hit, the trusted files and the remaining
  changed files in the job summary. Permissions: `contents: read`, `pull-requests: read`.
- **`.github/workflows/family-review.yml`** runs the Claude Code action
  (`anthropics/claude-code-action@v1`) under the Claude GitHub App's identity. It applies
  `docs/review-checklist.md` from `main` of `xippios/sdk-core`, in order, to the pull
  request's diff, reading the conventions, the definition of done and the ADRs from
  `sdk-core`'s `main` (never from the pull request) and the pull request's own
  `docs/upstream/` for every claim about the upstream. It judges the description's
  definition-of-done checklist and `Decisions taken` block and returns a JSON verdict,
  `ready` or `not ready`, with findings. `ready` passes; `not ready` fails the check and
  posts the findings as one PR comment. Permissions: `contents: read`,
  `pull-requests: write`, `id-token: write`. Until the org secret `ANTHROPIC_API_KEY`
  exists, the job writes a notice and ends green, and no ruleset requires it; a pull
  request from a fork never gets the secret, so its review fails instead of passing
  unreviewed.
- **`.github/workflows/ci.yml`** is this repository's own `ci`: ruff and the classifier's
  tests. It also calls `merge-class.yml` as a job, which proves the caller wiring below.

## Merge classes

The rules, in order. Every rule is evaluated and every reason lands in the summary; the
first `human` decides the class.

1. **Scaffold**: the base has no `src/` directory: `human`.
2. **Render trust**: the template is rendered at the head's `_commit` of
   `.copier-answers.yml` with the head's answers
   (`uvx copier copy --defaults --trust --skip-tasks --vcs-ref <_commit> --data-file
   <answers without _commit and _src_path>`). A changed file the template owns (rendered
   and matched by no `_skip_if_exists` pattern of the template's `copier.yml` at that
   ref) that is byte-identical to the render leaves the changed set. A file the template
   does not render, a skip-listed file and a deleted file are never trusted. Nothing is
   trusted when the render fails, when `_src_path` is not
   `https://github.com/xippios/sdk-template.git`, or when `_commit` is not on the
   template's `main`.
3. **Protected paths** in what remains: `human`. Everywhere: `.github/**`,
   `.claude/settings.json`, `.pre-commit-config.yaml`, `.secrets.baseline`,
   `docs/conventions.md`, `docs/adr/**`, `docs/review-checklist.md`. In `sdk-core`, also
   `src/**`. In `sdk-template`, also `copier.yml`, `scripts/**`, `template/.github/**`,
   `template/.claude/settings.json`, `template/.claude/commands/**`,
   `template/.pre-commit-config.yaml`, `template/.secrets.baseline`, and
   `template/pyproject.toml.jinja` when its `[project]` dependencies or its
   optional-dependencies change. In this repository, every pull request.
4. **First surface**: a `src/xippios/**/tasks.py` whose `__all__` was empty or absent
   names at least one task: `human`. An `__all__` that cannot be read statically is
   `human` too.
5. **Release**: when the `[project]` version of `pyproject.toml` changes, what remains
   must be a subset of `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, `README.md`,
   `CLAUDE.md`, `docs/handover.md` and `scripts/check-siblings.sh`; else `human`.
6. Otherwise **`auto`**.

The changed set and the comparisons of rules 3 to 5 are taken against the merge base of
base and head, which is the base itself once the pull request is up to date with its
branch (the required checks are strict). The classifier reads the pull request as git
objects and executes nothing from it.

## Wiring and check contexts

"Require workflows to pass before merging" may be an Enterprise-only ruleset rule, so both
workflows carry `on: pull_request` (types `opened`, `synchronize`, `reopened`) and
`on: workflow_call` (decided 2026-10-26). The ruleset editor decides which wiring applies.

| Wiring | Merge class check | Review check |
| --- | --- | --- |
| Required workflow (a ruleset requires the workflow from this repository, `ref` `main`) | `merge-class` | `family-review` |
| Caller (a repository's `ci.yml` calls the workflow as a job) | `merge-class / merge-class` | `family-review / family-review` |

In caller mode a repository's `ci.yml`, which runs on `pull_request`, adds these two jobs;
the `if` keeps them off `push` runs, which carry no pull request:

```yaml
  merge-class:
    if: github.event_name == 'pull_request'
    uses: xippios/.github/.github/workflows/merge-class.yml@main
    permissions:
      contents: read
      pull-requests: read

  family-review:
    if: github.event_name == 'pull_request'
    uses: xippios/.github/.github/workflows/family-review.yml@main
    secrets: inherit
    permissions:
      contents: read
      pull-requests: write
      id-token: write
```

## Rulesets

- **`sdk-main-protection`** (org branch ruleset on `main` of the `sdk-*` repositories,
  and of this repository once it joins the list): pull request required, `ci` required and strict,
  `family-review` required once the org secret `ANTHROPIC_API_KEY` exists, no approvals
  required (the App cannot approve), no bypass actor.
- **`sdk-merge-class`** (org branch ruleset, same targets): requires the merge-class check
  and nothing else. Bypass actor Johannes, mode "pull requests only": the bypass button is
  how a `human` pull request merges, and it bypasses nothing but the class. In caller mode
  it is created once every repository's `ci.yml` carries the `merge-class` job.
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
files; `--summary <file>` appends the markdown summary, `--no-render` skips rule 2 (nothing
is trusted), `--template-url` points rule 2 at another template clone. Exit status: 0
`auto`, 1 `human`, 2 when the classification itself failed.

The checks of this repository:

```sh
uvx ruff check scripts && uvx ruff format --check scripts
uv run --no-project --with pytest pytest scripts/tests -q
```

## Changing this repository

Every pull request here is `human`, so Johannes merges each one: no session can change the
class computation or the review gate. The review checklist itself lives in `sdk-core`
(`docs/review-checklist.md`), where it is a protected path too.
