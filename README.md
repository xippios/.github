# xippios/.github

The organization's `.github` repository: its defaults, the issue forms under
`.github/ISSUE_TEMPLATE/` and the pull request template of every repository, and the
reusable workflows that a repository calls as jobs. The coordinate workspaces call
`spelling.yml`, the spelling check (C79), from coordinate-core 0.5.1, and
`conventions.yml`, the conventions review by mode on each repository's own documents, from
coordinate-core 0.6.4 (C57 as amended by coordinate-core#364, .github#32); `adr-index.yml`
checks a repository's index of its decision records. The conventions
review keeps its place beside the reviewer for good (C57). GitHub decides what merges: the
required checks pass, the required approvals are there, and auto-merge merges. The sites of the
web workspace call `site-tests.yml`, which runs a site's suite through the host xippios-web,
from web-template 0.1.0 (https://github.com/xippios/.github/issues/30).

Names: created as `xippios/.github`, renamed `xippios/sdk-gates` on 2026-10-27 and back to
`.github` on 2026-10-30 for the coordinate workspaces (coordinate-core plan §11.2); the
clone in the coordinate root is `defaults`. GitHub redirected the old name until 2026-11-03,
so `conventions.yml` checks the repository out by its name, `xippios/.github` (gap
.github#16), into the directory still named `.sdk-gates`.

## The forms

The issue forms under `.github/ISSUE_TEMPLATE/` and `.github/pull_request_template.md` are
written by the coordinate workspace's adoption run from `docs/style/issues.md` and `pulls.md` of
the coordinate-core release it adopts, from 0.6.4 on, and arrive as that run's pull request (C73,
C74). A form has one field per section of
its template, in the same order and with the same names. It carries its issue type and no title
prefix, and it has no field for who filed, since the account and the `by:` label say that (C62).
Each file's header names the release it was written from: a form changes in the core's style and
its next release, never here. The generator this repository kept until then left with
https://github.com/xippios/.github/issues/33. `config.yml` stays by hand.

## The workflows

- **`.github/workflows/spelling.yml`** (coordinate-core 0.5.1, C79, .github#18) is the
  spelling check of the coordinate workspaces: a reusable workflow a repository's `gates.yml`
  calls as a job with the paths to check, check `spelling / spelling`. It runs codespell,
  pinned to 2.4.3, with its built-in `en-GB_to_en-US` dictionary only, so a British spelling
  fails it and a typo does not (the typo dictionaries flag identifiers). Three flags widen
  codespell's defaults to what C79 covers: `--regex` splits words at every non-letter and at a
  camelCase hump, so a possessive, a snake_case and a camelCase name are checked by their
  parts; `--check-hidden` checks `.claude` and `.github`, which codespell skips even when named;
  `--skip .git` keeps a caller that names `.` out of the repository's objects. The caller's
  `gates.yml` alone decides what is checked: codespell runs from the runner's temporary
  directory, so no `.codespellrc`, `setup.cfg` or `pyproject.toml` of the checkout is read, and
  uv runs with `--no-config`. `ignore-words` defaults to `cancelled`, GitHub's spelling of a
  run's conclusion and of `cancelled()`. A named path that does not exist fails the check,
  since codespell passes it in silence. Permissions: `contents: read`; no secret. The job times
  out after 5 minutes. A root's caller:

  ```yaml
  spelling:
    uses: xippios/.github/.github/workflows/spelling.yml@main
    with:
      paths: rules docs/style docs/adr docs/adr.md docs/adr.json docs/reports README.md CLAUDE.md .claude workspace.toml labels.yml
  ```

  A line that must keep a British word, such as a compatibility read of an old key, carries
  codespell's inline `codespell:ignore` comment.
- **`.github/workflows/conventions.yml`**, the conventions review (C57 as amended by
  coordinate-core#364, check `conventions`): it judges a pull request against its repository's
  own documents, while the reviewer judges it against the plan of its package. It runs
  `scripts/conventions.py`, which has `claude-opus-5-5`, at effort `xhigh`
  (https://github.com/xippios/.github/issues/93), review the pull request on the Messages API
  (the SDK `anthropic`, pinned to 2.3.0), each turn streamed with `max_tokens` 64,000, since
  thinking counts against it. The verdict, `ready` or `not ready`, comes back with its findings
  through a `submit_verdict` tool. `ready` passes and `not ready`
  fails the check, and every verdict, `ready` included, goes to one sticky PR comment, created
  when the workflow token wrote none and edited in place on the next run, never over another
  workflow's comment, in the form of `docs/style/reviews.md#conventions-check` of a coordinate
  root: the lead with the count and the head's commit, what was judged, then the findings, each
  with the document and the section it goes against. A run that reviews nothing posts none, and
  a post that fails leaves its reason in the job summary and a warning annotation. No verdict (an
  API error, a refusal, a `max_tokens` stop, the turn cap of 160, a missing key) fails the check,
  and the job summary carries the script's line with the cause (the SDK's error class and its
  redacted message, a refusal's category), the turns, the tool calls, the token usage and the
  key the review ended on (the keys below).
  Permissions: `contents: read`, `pull-requests: write`, `checks: read`.
  - **The release pull request** (https://github.com/xippios/.github/issues/47): one labeled
    `release`, or titled `<version> Release`, and `release: <version>` until every workspace has
    adopted coordinate-core 0.7.4 (`docs/style/pulls.md#release-pr` of a coordinate root), on
    any branch. The job's own `if:`
    skips any other pull request unless the mode is `all` or a value the Gate refuses, so a
    caller needs no condition of its own: its check `conventions / conventions` reports as
    skipped and passing, and no runner starts. GitHub's expressions know no regular expression
    and compare without case, so the condition admits a title by its start, `release:` and a
    space, or by its end, a space and `Release`, and the Gate below matches it exactly. A caller
    runs on no label, so a label set after the opening counts from the next push or edit.
  - **The mode**: the caller's variable `CONVENTIONS_REVIEW`, read from the calling repository,
    where a repository variable overrides the organization's by GitHub's precedence, and read
    without case by the condition and the Gate alike, so `Off` is `off`. `release`, the default
    when neither is set, reviews a release pull request. `all` reviews every pull request. `off`
    reviews none. Any other value fails the check and names the three. A pull request the
    condition skips gets no notice, since no job runs; one it admits that the mode does not
    review passes with the Gate's notice. A pull request that no mode reviews makes no API call
    and needs no key. The mode reads the title and the label, so a caller runs on `edited` too,
    and a label set after the opening counts from the next push or edit.
  - **The documents**: the ones the repository's `README.md` links under `## Documents`, read on
    the default branch and never from the pull request, so a pull request cannot rewrite the
    rules it is judged by (C80, `docs/style/repository.md` of a coordinate root). A path, an
    anchor and a URL of the repository itself are read from its default branch; a URL of another
    repository's file is read from GitHub with the workflow's token, which reads a public
    repository, and where GitHub does not find the file with it, with the read token below,
    which a private caller passes. A document that neither reads fails the check, naming the
    document and the tokens it was read with. It is read at the ref its link names, unless the
    head of the pull request
    requires that repository's package in the `[project]` dependencies or optional
    dependencies of its `pyproject.toml` and the link names a branch: then it is read at the
    highest release tag of that repository, `v` and a release version, that the requirement
    admits, as `~=0.3.0` admits `v0.3.2` and no `v0.4.0`
    (https://github.com/xippios/.github/issues/70, as the human decided in
    https://github.com/xippios/.github/issues/74). The requirement is the head's, so a
    repository is judged by the documents of the release it is on, and the pull request that
    raises its requirement is the first judged by the newer ones
    (https://github.com/xippios/.github/issues/75). The package's name comes from that
    repository's own `pyproject.toml`, so the check names no repository; one that GitHub does
    not find, with the read token too where the caller passes one, means no package. A link
    that names a tag or a commit, and a repository whose package the head does not require,
    are read at the link's ref. Where no release tag fits, or the requirement names no version
    the check compares (a
    release version after `~=`, `==`, `!=`, `<=`, `>=`, `<` or `>`, `.*` after `==` and
    `!=`), or GitHub does not find the file in that release, the link's ref stands and the job
    summary says so. That repository's tags, and its `pyproject.toml` for any reason but "not
    found", that cannot be read fail the check, naming the repository, and so does a document
    that the release fails to serve for any reason but "not found", naming the document. The
    job summary and `documents.json` name the ref each document was read at. A link the review
    cannot read as a file, a directory or a page outside GitHub, fails the check naming it. A
    README that links none passes with the notice "links no documents under ## Documents;
    nothing to judge", since the root's `doctor` owns that contract.
  - **The read token** (https://github.com/xippios/.github/issues/62): `DOCUMENTS_READ_TOKEN`,
    an optional secret of the caller, a token that reads the private repositories whose files
    its README lists. The check uses it only where the calling repository is private, by
    `github.event.repository.private` of the caller's event, as the human decided in
    https://github.com/xippios/.github/issues/83. The review's comment and its job summary
    quote the documents it judges by, so in a public repository they would publish a private
    document's text, and in a private repository they can show the sibling's text to everyone
    who reads that repository. A public repository that passes the secret reads as one that
    passes none, and its job summary says so where the review runs: a private sibling's
    document fails its check and names it. Where the check uses the token, it asks GitHub for
    another repository's file with the workflow's token first, and only where GitHub answers
    "not found" asks again with the read token: for a listed document, that repository's
    `pyproject.toml` and its tags, so a private repository's document is read and its pin
    resolves as a public one's does. Any other failure fails the check as above, and the read
    token never stands in for it. Without the secret, or with it empty, the check reads with
    the workflow's token alone. The token is in the environment of the step that prepares the
    review material alone, and the script hands it to `gh` as the `GH_TOKEN` of that one read,
    so no other process gets it, the review's included, and neither the job summary,
    `documents.json` nor the log carries it. Of what the check reads with the token, a pull
    request chooses nothing but a release tag, by the requirement of its head: the list of
    documents comes from the README on the default branch, never from the pull request. That
    bounds the check, not the secret: a changed workflow of any repository that receives the
    secret can use it otherwise, and which repositories receive it is the organization's
    setting. A pull request from a fork or of Dependabot gets no secret, and the Gate below
    ends it before any read.
  - **The range**: on a release pull request the review judges everything from the last release
    tag (`v*`) reachable from the base to the head, since the pull request's own diff is the
    CHANGELOG and the bump. Without a tag it judges the pull request's own diff and says so. Any
    other pull request is judged on its own diff, merge base to head.
  - **The version**: the review names the version a release pull request ships, read from its
    title, else from the `[project]` version of the head's `pyproject.toml`, taken from the
    commit and in a version's characters only. Where neither names one, the job summary says
    so and the review runs without it.
  - **The Messages API**: the review left the Claude Code action for the Messages API, called
    with an API key, on 2026-10-29 (D101 to D103).
  - **Where the script comes from**: this repository, checked out into `.sdk-gates` at
    `job.workflow_sha`, the commit of the workflow file that defines the job: for a caller,
    the commit its `uses:` resolved to (`@main`). The review no longer runs on this
    repository's own pull requests (C58). actionlint 1.7.12 does not know the property yet, so
    `.github/actionlint.yaml` ignores that one error in `conventions.yml`.
  - **Identity**: the review runs on the workflow token (`github.token`), so its comment
    comes from `github-actions[bot]`. It did so under the action too, whose Claude GitHub
    App token exchange skips every pull request whose calling workflow differs from the
    one on the default branch, which would have left adoption PRs without a verdict
    (decided 2026-10-26).
  - **Gate**, in order: a Dependabot pull request (its author and the triggering actor both
    `dependabot[bot]`) ends green with the notice "conventions: Dependabot PR, reviewed by
    `ci` only", since Dependabot runs get no Actions secrets. A pull request the job's
    condition admits and the mode does not review ends green with its notice. A pull request
    opened or updated by any other GitHub App (a login ending in `[bot]`) gets no review and
    fails by design, with
    "conventions: a pull request opened or updated by a GitHub App gets no review", as the
    action's empty `allowed_bots` had it. Every other pull request needs the organization
    secret `ANTHROPIC_API_KEY`, shared with every repository (coordinate-core#368): a pull
    request from a fork never gets it and fails, and one from the repository itself with the
    secret empty fails naming it.
  - **The keys** (https://github.com/xippios/.github/issues/87): `ANTHROPIC_API_KEY` holds one
    key or several, one per line, and the script tries them in that order. A blank line and
    the spaces around a key are dropped, and the SDK gets one key at a time, never the value
    of several lines. A review runs on one key from its first turn to its verdict. Where the
    API refuses the key or its account, at the first request or a later one, the review
    starts again from its first turn on the next key, and no conversation moves to another
    key. A refusal is the API's authentication, permission or billing error or its rate
    limit, known by the status (401, 403, 402, 429) or by the error type that an error event
    of the stream carries (`authentication_error`, `permission_error`, `billing_error`,
    `rate_limit_error`), and a 400 whose message names the balance of the account. A 429
    reaches the script only once the SDK's own retries are spent, while the SDK retries no
    stream it has begun, so a `rate_limit_error` that an error event of the stream carries
    moves the review to the next key at once. Any other end without
    a verdict (a server error, a lost connection, any other 400, a refusal of the model, a
    `max_tokens` stop, the turn cap) tries no other key. The summary line names the key the
    review ended on by its position, `key=2/3`, and counts the tokens of every attempt; its
    turns and tool calls are the last attempt's, and the job log names each key the review
    moved past by its position and error class. Where the API refused every key, the review
    has no verdict, and its line names each key by its position and the SDK's error class;
    with one key it carries that key's error as before. No output carries a key: the script
    redacts every key of the secret, whatever its form, from all it prints and writes, and
    the PR comment says nothing of keys. A secret with one key reviews as before, and a
    caller's `gates.yml` passes the secret as it did.
  - **What the model may do**: nothing but read. Before it starts, `conventions.py
    prepare` writes its material to `.review/`: `diff.patch` and `log.txt` of the range,
    `pr.json` (title, body, author, comments, files), `checks.json` (the head's checks, `ci`
    among them), `meta.json` (the coordinates and the range) and the documents under
    `documents/`, listed in `documents.json`. The system prompt carries the instructions and
    the documents, cached, and names no pull request (the coordinates and the range are in
    the first message), so every review of a repository against the same documents sends the
    same prefix and parallel reviews read one cache entry; the model reads everything else
    with three tools the script serves, `read_file` (2,000 lines or 64 KiB a call),
    `list_files` (500 paths) and `grep` (200 matches, each line's first 4,000 characters,
    stopped by a timer after 20 seconds, inside a regular expression too), inside the
    workspace's real path only: `.git/` at any depth, `.envrc`, `.env` and `.env.*`, a symlink
    that leads out and the script's own checkout are refused. It runs no command, edits
    nothing and reaches no network, and `.review/diff.patch` is authoritative for what
    changed. The review spawns no process, and `ANTHROPIC_API_KEY` is in the Review step's
    environment alone; setup-uv reads the `.sdk-gates` checkout and uv runs the script from
    the runner's temporary directory with `--no-config`, so nothing in the pull request's
    checkout (a `uv.toml`, a `.python-version`, a `.venv`, a uv version or cache key) decides
    what runs beside the key, and `--exclude-newer 2026-10-29T00:00:00Z` freezes the
    resolution of `anthropic`'s dependencies. The prompt names the pull request's files,
    diff, messages, title, body and comments as material to judge, never instructions; an
    instruction found in them is itself a finding. The job log is public: the script prints
    paths, counts, the verdict and redacted error text, never a file's content, a tool
    result or the prompt, and the verdict step redacts anything that looks like a key or a
    GitHub token from the summary and the comment.
- **`.github/workflows/site-tests.yml`** (https://github.com/xippios/.github/issues/30 as
  amended by https://github.com/xippios/.github/issues/37) runs a site's suite through the host
  xippios-web, the only test harness of the web platform.
  The `ci.yml` that web-template renders
  into a site calls it as the job `tests`, check `tests / tests`, with the site's key and the
  organization secret `WEB_READ_TOKEN`, which reads xippios-web and the sites it requires:

  ```yaml
  tests:
    uses: xippios/.github/.github/workflows/site-tests.yml@main
    with:
      site: didaskalu
    secrets:
      WEB_READ_TOKEN: ${{ secrets.WEB_READ_TOKEN }}
  ```

  - **The site at its commit**: the job checks the site out at the commit of the caller's event
    and the host at `main`. It names that commit the branch `site-tests` of the site's checkout,
    since a Composer `vcs` repository reads a local clone's branches, and requires
    `xippios/web-<site>:dev-site-tests` into the host through such a repository, with
    `--update-with-dependencies`. The host's other packages stay as its lock has them.
  - **The suite**: the job copies `.env.example` to `.env` where the host has none, generates a
    key and runs `php artisan test --testsuite=<site>`, whose pages render without the Vite
    build, since the host's `Tests\TestCase` calls `withoutVite()`. Where the site has
    `tests/Browser`, it then builds the host's assets with `npm ci --ignore-scripts` and
    `npm run build` (https://github.com/xippios/.github/issues/69): the host's `vite.config.js`
    takes the site's entries from `vendor/xippios/web-<site>`, where the require put the site,
    and the host's layout loads them from `public/build/manifest.json`, without which a site's
    page answers 500. No install script of a package runs, as the host's `.npmrc` also sets it.
    Then it runs `php artisan dusk --testsuite=<site>` against the host served by
    `php artisan serve` at `APP_URL` `http://127.0.0.1:8000`, Laravel's recipe for Dusk on
    GitHub Actions. Where the site has no `tests/Browser`, no npm runs and a notice says that
    Dusk does not run. The suites are the host's, one per site in its `phpunit.xml` and
    `phpunit.dusk.xml`, from xippios-web 0.1.0.
  - **The checks before**: an empty secret fails the check and names it. A pull request from a
    fork never gets the secret, so it fails there. A key that web-template's `copier.yml` would
    refuse fails, and so does a site whose `composer.json` names another package than
    `xippios/web-<site>`.
  - **The token** reaches two steps only: the host's checkout, which keeps no credential, and
    Composer's resolution, which runs with `--no-scripts` and `--no-plugins` and gets the token
    in `COMPOSER_AUTH`, never on disk. The skipped scripts, package discovery among them, the
    plugins the host allows, the suite, the build and Dusk run after it, without the token. The
    build needs none: the host's `package-lock.json` takes every package from the public npm
    registry, and its `.npmrc` names no registry and no credential.

  PHP 8.4 and Composer 2.11.1 come from setup-php, and Node 22, the version the host's own
  `ci.yml` builds with, from setup-node, with no cache. Permissions: `contents: read`. The job
  times out after 20 minutes.
- **`.github/workflows/adr-index.yml`**
  (https://github.com/xippios/.github/issues/46) checks that a repository's index of its
  architecture decision records is current: `docs/adr.md` and `docs/adr.json` must be what the
  repository's own `scripts/adr_index.py` writes from the records in `docs/adr/`, and no two
  records may take one number. A repository's `gates.yml` calls it as a job, check
  `adr-index / adr-index`, with no input and no secret:

  ```yaml
  adr-index:
    uses: xippios/.github/.github/workflows/adr-index.yml@main
  ```

  - **The script is the caller's**: the template of a coordinate repository renders
    `scripts/adr_index.py`, and the job runs that file from the checkout, never a copy of its
    own, with `--check`, which writes nothing and exits 1 when either file differs from the
    records or a record does not read. The runner's `python3` runs it with `-I`, as `coordinate`
    does, since the script needs the standard library alone. A caller without the script fails,
    naming it.
  - **A number twice**: the job reads the records' numbers itself, from the names
    `docs/adr/NNNN-<slug>.md` the script reads, so two records with one number fail the check
    whatever the caller's script checks, each pair named. On a pull request the checkout is its
    merge with the base, so a number the base took since the branch left it counts as taken.
  - **The failure names the script**: each error annotation names
    `python3 scripts/adr_index.py`, which writes both files from the records, to be run and its
    files committed once what comes first is mended. After a failed `--check` that is any record
    the script's own lines above the annotation name, such as one whose first line does not
    read, since the script writes neither file while a record does not read; after a number
    twice, one of the two records renumbered. A record's name reaches an annotation escaped, so
    no name starts a workflow command.

  Permissions: `contents: read`; the checkout keeps no token. The job times out after 5 minutes.
- **`.github/workflows/ci.yml`** is this repository's own `ci` (15 minutes): ruff 0.17.1,
  the scripts' tests on a pinned pytest (with the review's
  `anthropic` 2.3.0 and `spelling.yml`'s codespell; a fake client, no key, no network), and
  actionlint with the runner's shellcheck. It calls `spelling.yml` over `README.md`, `.github`
  and `scripts` as the job `spelling`, and `ci` fails when that job did not pass, so the
  ruleset's required check `ci` covers both. The one test of `site-tests.yml` that requires a
  site with the real Composer uses the runner's PHP and Composer, and is skipped elsewhere
  without them.

Every action in the workflows is pinned to a commit SHA with its version in a comment.
`setup-uv` installs a pinned uv and `setup-php` a pinned Composer, the review runs a pinned
`anthropic`, and the spelling check a pinned codespell.

## Wiring and check contexts

The reusable workflows carry `on: workflow_call` alone (C58, 2026-11-03): a repository calls
them as jobs from a workflow of its own beside `ci.yml`, a coordinate root's
`.github/workflows/gates.yml` or an sdk source's `organization.yml`, and a site calls
`site-tests.yml` from the `ci.yml` that web-template renders. On this repository's own pull
requests only `spelling.yml` runs, called by `ci.yml`.

From coordinate-core 0.7.6 and sdk-template 0.3.4 on, the caller of `spelling.yml`,
`conventions.yml` and `adr-index.yml` runs on `pull_request` with the types `opened`,
`synchronize`, `reopened` and `edited`. A caller's `on: pull_request` without `types` runs on the
first three only, and `edited` matters to the review, since the description is judged and a
change of the title or of the base arrives as `edited`. A caller runs on no label (C57):
GitHub starts a workflow on a label of any name and reports a head's checks from its newest
run, so the run of a label could stand for the head. A label set
after the opening, `release` among them, counts from the next push or edit. The caller's jobs
carry no `if:`, so each run reports every check: the review's job decides in its own condition,
under `conventions.yml` above, and its check reports skipped and passing on a pull request that
condition skips (https://github.com/xippios/.github/issues/47).

| Workflow | Caller job | Check context |
| --- | --- | --- |
| `spelling.yml` | `spelling` | `spelling / spelling` |
| `conventions.yml` | `conventions` | `conventions / conventions` |
| `adr-index.yml` | `adr-index` | `adr-index / adr-index` |
| `site-tests.yml` | `tests` | `tests / tests` |

A context joins the caller's job id and the callee's job name, so a ruleset requires the
slash-joined context and a caller keeps the job ids above. The caller passes the review its
secrets by name, never `secrets: inherit`: `ANTHROPIC_API_KEY`, and `DOCUMENTS_READ_TOKEN` in a
private repository whose README lists a private repository's document (the read token under
`conventions.yml` above). It grants the permissions the review asks; a caller that grants less
fails at the start:

```yaml
name: gates

on:
  pull_request:
    types: [opened, synchronize, reopened, edited]

permissions:
  contents: read

jobs:
  spelling:
    uses: xippios/.github/.github/workflows/spelling.yml@main
    with:
      paths: rules docs/style docs/adr docs/adr.md docs/adr.json docs/reports README.md CLAUDE.md .claude workspace.toml labels.yml

  conventions:
    uses: xippios/.github/.github/workflows/conventions.yml@main
    permissions:
      contents: read
      pull-requests: write
      checks: read
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      # Only in a private repository whose README.md lists a private repository's document.
      DOCUMENTS_READ_TOKEN: ${{ secrets.DOCUMENTS_READ_TOKEN }}
```

## Rulesets

The organization's ruleset on this repository (gate coordinate#9;
`gh api orgs/xippios/rulesets`):

- **`GitHub Main`** (org branch ruleset on `main` of this repository): pull request
  required, one approving review, review from code owners (`.github/CODEOWNERS` names
  the human for every path), stale approvals dismissed on push, `ci` and `review` required,
  merge or squash. The review does not run here (C58); `ci` calls `spelling.yml` over this
  repository's files.

## Running the checks locally

The checks of this repository, as `ci` runs them:

```sh
uvx ruff@0.17.1 check scripts && uvx ruff@0.17.1 format --check scripts
uv run --no-project --with pytest==9.1.1 --with anthropic==2.3.0 --with codespell==2.4.3 pytest scripts/tests -q
uvx --from actionlint-py==1.7.12.25 actionlint
```

`ci` runs actionlint with the runner's shellcheck; locally, add it with
`uvx --from actionlint-py==1.7.12.25 --with shellcheck-py sh -c actionlint`.

## Running the review locally

A dry run clones the pull request into a temporary directory (or `--workdir`, kept), prepares
the material as the workflow does, the documents from the clone's `origin/main` (`--main`
names another ref) and a pull request labeled `release` or titled `<version> Release` or
`release: <version>` on its release's range, with its version, and runs the review, then
prints the summary line and the findings, each with the document it goes
against. A README that links no documents ends it there, green, as in the workflow. It needs
`gh` signed in, whose login stands for the workflow's token, and a `DOCUMENTS_READ_TOKEN` in the
environment of the command is read as a private caller's workflow reads the secret, whatever the
repository's visibility, since a dry run posts nothing. It needs the key in the
environment of that one command, never on disk or in the shell's history, and tries a value
of several lines key by key as the workflow does: `read -rs` prompts for one key without
echo:

```sh
read -rs K && ANTHROPIC_API_KEY="$K" uv run --no-project \
  --exclude-newer 2026-10-29T00:00:00Z --with anthropic==2.3.0 \
  python <this clone>/scripts/conventions.py dry-run --repo xippios/<repo> --pr <n>
unset K
```

`--model`, `--effort` and `--max-turns` change the judge, its effort and the turn cap;
`--out` also writes the verdict file. Exit status: 0 `ready`, 1 `not ready`, 2 no
verdict.

## Changing this repository

Every pull request here waits for the human: the `GitHub Main` ruleset wants the human's
code-owner approval (below) and `ci` and `review` green, so no session can change the workflows
or the review on its own. A pull request that changes `conventions.py` is checked by `ci`
and the dry run above; the review no longer runs on this repository's own pull requests
(C58). The documents the review judges by are each repository's own, listed in its README's
`## Documents` (C80), so nothing here decides what a repository is held to.

`.github/CODEOWNERS` names the human for every path, so the organization ruleset's code-owner
review (gate coordinate#9: one approval, review from code owners, stale approvals dismissed on
push) is the human's approval on every pull request here. The reviewer's approval sets the
required status `review` beside it, never in its place. `coordinate sync` writes the root's
CODEOWNERS from `workspace.toml`; this repository's is kept by hand.
