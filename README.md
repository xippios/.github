# xippios/.github

The organization's `.github` repository: its defaults, the issue forms under
`.github/ISSUE_TEMPLATE/` and the pull request template of every repository, and the
reusable workflows that a repository calls as jobs. The coordinate workspaces call
`spelling.yml`, the spelling check (C79), from coordinate-core 0.5.1, and
`conventions.yml`, the conventions review by mode on each repository's own documents, from
coordinate-core 0.6.4 (C57 as amended by coordinate-core#364, .github#32); `adr-index.yml`
checks a repository's index of its decision records. The conventions
review keeps its place beside the reviewer for good (C57). The sites of the web workspace call
`site-tests.yml`, which runs a site's suite through the host xippios-web, from web-template
0.1.0 (https://github.com/xippios/.github/issues/30).

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

- **`.github/workflows/spelling.yml`** checks that the files its caller names are spelled in
  American English, check `spelling / spelling`. It runs on a pull request's opening, push and
  reopening, as its trigger file starts it. The calling file hands over the input `paths`, the
  files and directories to check, separated by spaces or newlines, the optional input
  `ignore-words`, and no secret. Permissions: `contents: read`. The variable
  `WORKFLOW_SPELLING` switches it (the switch, under the wiring below).

  It runs codespell, pinned to 2.4.3, with its built-in `en-GB_to_en-US` dictionary only, so a
  British spelling fails it and a typo does not (the typo dictionaries flag identifiers). Three
  flags widen codespell's defaults to what C79 covers: `--regex` splits words at every non-letter
  and at a camelCase hump, so a possessive, a snake_case and a camelCase name are checked by their
  parts; `--check-hidden` checks `.claude` and `.github`, which codespell skips even when named;
  `--skip .git` keeps a caller that names `.` out of the repository's objects. The caller's
  `gates.yml` alone decides what is checked: codespell runs from the runner's temporary directory,
  so no `.codespellrc`, `setup.cfg` or `pyproject.toml` of the checkout is read, and uv runs with
  `--no-config`. `ignore-words` defaults to `cancelled`, GitHub's spelling of a run's conclusion
  and of `cancelled()`. A named path that does not exist fails the check, since codespell passes
  it in silence; a path is read under the caller's checkout, so an absolute path does not exist
  there. The job times out after 5 minutes. A root's caller:

  ```yaml
  spelling:
    uses: xippios/.github/.github/workflows/spelling.yml@main
    with:
      paths: rules docs/style docs/adr docs/adr.md docs/adr.json docs/reports README.md CLAUDE.md .claude workspace.toml labels.yml
  ```

  A line that must keep a British word, such as a compatibility read of an old key, carries
  codespell's inline `codespell:ignore` comment.
- **`.github/workflows/conventions.yml`**, the conventions review, judges a pull request
  against its repository's own documents, check `conventions / conventions`. It runs on a pull
  request's opening, push, reopening and edit, and on no other event of its caller (the events,
  below). The calling file hands over the secrets `ANTHROPIC_API_KEY` and
  `DOCUMENTS_READ_TOKEN`, both optional, by name, and no input. Permissions: `contents: read`,
  `pull-requests: write`, `checks: read`. The variable `WORKFLOW_CONVENTIONS` switches it (the
  switch, under the wiring below).

  Beside it, the reviewer judges a pull request against the plan of its package. The review runs
  `scripts/conventions.py`, which has `claude-opus-5-5`, at effort `xhigh`
  (https://github.com/xippios/.github/issues/93), review the pull request on the Messages API
  (the SDK `anthropic`, pinned to 2.3.0), each turn streamed with `max_tokens` 64,000, since
  thinking counts against it. The verdict, `ready` or `not ready`, comes back with its findings
  through a `submit_verdict` tool. `ready` passes and `not ready`
  fails the check, and every verdict, `ready` included, goes to one sticky PR comment, created
  when the workflow token wrote none and edited in place on the next run, never over another
  workflow's comment, in the form of `docs/style/reviews.md#conventions-check` of a coordinate
  root: the lead with the count and the head's commit, what was judged, then the findings, each
  with the document and the section it goes against and the sentence it quotes (the quote,
  below), and after a run before, its findings with what became of each (the run before,
  below). A run that reviews nothing posts none, and a post that fails leaves its reason in the
  job summary and a warning annotation. No verdict (an
  API error, a refusal, a `max_tokens` stop, the turn cap of 160, a missing key) fails the check
  and posts no comment: the Review step fails without ending the job, and the Verdict step after
  it reads the verdict file and decides the check. The job summary carries the script's line
  with the cause (an API error's class and its request's id, a refusal's category), the
  turns, the tool calls, the token usage and the key the review ended on (the keys below). An
  API error is named by the SDK's error class and the request's id where the error carries one,
  never by the upstream's message, in the job log and the job summary alike, on a pull request,
  on a range and in a dry run (https://github.com/xippios/.github/issues/121). The job
  times out after 45 minutes, which leaves a review at effort `xhigh` the time of 160 turns on one
  key; a review the timeout ends returns no verdict and writes no summary line. A new push or edit
  of the pull request cancels the run that still reviews its state before.
  - **The events**: the job runs on a pull request's opening, push, reopening and edit alone,
    the event `pull_request` with the types `opened`, `synchronize`, `reopened` and `edited`,
    and is skipped on any other event of its caller, such as a push to `main`, a dispatch or the
    closing of a pull request. A called workflow reads its caller's event, `github.event_name`
    and `github.event.action`, so a caller that also runs on a push to `main` or on a dispatch
    starts no review there and its check reports as skipped, and a caller that runs on those
    four alone sees no change.
  - **The release pull request** (https://github.com/xippios/.github/issues/47): one labeled
    `release`, or titled `<version> Release` (`docs/style/pulls.md#release-pr` of a coordinate
    root), on any branch. The job's own `if:`
    skips any other pull request unless the mode is `all` or a value the Gate refuses, so a
    caller needs no condition of its own: its check `conventions / conventions` reports as
    skipped and passing, and no runner starts. GitHub's expressions know no regular expression
    and compare without case, so the condition admits a title by its end, a space and
    `Release`, and the Gate below matches it whole, stripped of white space at its ends. A caller
    runs on no label, so a label set after the opening counts from the next push or edit.
  - **The mode**: the caller's variable `WORKFLOW_CONVENTIONS_MODE`, read from the calling
    repository, where a repository variable overrides the organization's by GitHub's
    precedence, and read without case by the condition and the Gate alike, so `All` is `all`.
    `release`, the default when neither is set, reviews a release pull request. `all` reviews
    every pull request. Any other value, `off` among them, fails the check and names the two. A
    pull request the condition skips gets no notice, since no job runs; one it admits that the
    mode does not review passes with the Gate's notice. A pull request that no mode reviews
    makes no API call and needs no key. The mode reads the title and the label, so a caller
    runs on `edited` too, and a label set after the opening counts from the next push or edit.
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
    nothing to judge" and makes no API call, since the root's `doctor` owns that contract.
  - **The read token** (https://github.com/xippios/.github/issues/62): `DOCUMENTS_READ_TOKEN`,
    an optional secret of the caller, a token that reads the private repositories whose files
    its README lists. The check uses it only where the calling repository is private, by
    `github.event.repository.private` of the caller's event, as the human decided in
    https://github.com/xippios/.github/issues/83. The review's comment and its job summary
    quote the documents it judges by, so in a public repository they would publish a private
    document's text, and in a private repository they can show the sibling's text to everyone
    who reads that repository. A public repository that passes the secret reads as one that
    passes none, and its job summary says so where the review runs, from the Gate, which learns
    whether the secret was passed and never its value: a private sibling's document fails its
    check and names it. Where the check uses the token, it asks GitHub for
    another repository's file with the workflow's token first, and only where GitHub answers
    "not found" asks again with the read token: for a listed document, that repository's
    `pyproject.toml` and its tags, so a private repository's document is read and its pin
    resolves as a public one's does. Any other failure fails the check as above, and the read
    token never stands in for it. Without the secret, or with it empty, the check reads with
    the workflow's token alone. The token is in the environment of the step that prepares the
    review material alone, as the empty string where the caller is public, and the script hands
    it to `gh` as the `GH_TOKEN` of that one read,
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
    other pull request is judged on its own diff, merge base to head. The head is checked out
    with its full history, which brings the default branch, where the README and its documents
    are read, and the release tags, where a release's range starts. Where a run judged a commit
    of that range, the review judges only what came after it (what a run builds on, below).
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
    `.github/actionlint.yaml` ignores that one error in `conventions.yml` and in
    `conventions-range.yml`, whose two jobs check the script out the same way.
  - **Identity**: the review runs on the workflow token (`github.token`), so its comment
    comes from `github-actions[bot]`. It did so under the action too, whose Claude GitHub
    App token exchange skips every pull request whose calling workflow differs from the
    one on the default branch, which would have left adoption PRs without a verdict
    (decided 2026-10-26).
  - **Gate** (`conventions.py gate`): it decides after the checkout of the script alone, so a
    pull request it turns away gets no checkout of its head, no key and no API call. In order:
    a Dependabot pull request (its author and the triggering actor both
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
    with one key it names that key's error by its class and the request's id. No output
    carries a key: the script redacts every key of the secret, whatever its form, from all it
    prints and writes, and
    the PR comment says nothing of keys. A secret with one key reviews as before, and a
    caller's `gates.yml` passes the secret as it did.
  - **The run before** (https://github.com/xippios/.github/issues/95): `prepare` reads the
    check's last comment on the pull request before the Verdict step rewrites it: the
    workflow token's, which `gh` names `github-actions`, opening with the check's marker. Its
    hidden last line, `<!-- conventions-run: … -->`, carries the head that run judged and its
    findings, as JSON with `<` and `>` escaped so that no text ends the HTML comment early.
    The head is compared with the one judged before by the text of its files, not by
    ancestry, since a rebased head descends from no head judged before: the two trees, the
    checkout's tree of the earlier head where it holds that commit, else GitHub's, read with
    the workflow's token, and a file changed where its blob or its mode differs.
    `.review/earlier.json` gives the review the findings of the run before, each with whether
    its file changed since, and the opener's decisions on the pull request, its author's
    comments marked `<!-- style: comments/decisions -->`; `.review/changed.json` holds the
    files changed since. The first message names the run before and the count of its
    findings, so the cached prefix stays the same for every review of the repository. The
    review gives each finding of the run before one state, fixed, decided by the opener or
    open, an open one with the number of the finding of this review that carries it, and the
    script answers another state, a finding left out or one given twice as it answers a
    malformed finding: the model calls again. `decided` needs a decision of the opener on the
    pull request. A decision of the opener settles a finding that did not block, and never
    settles a finding that blocked by itself: that one is `decided` only where the judge finds
    that the decision shows no written rule broken, and gives that reason in one sentence,
    which the comment prints with it; where the rule is still broken it is open, carried into
    this run as a finding, and the comment says that the opener decided otherwise and why the
    rule stands. The script refuses `decided` on a finding that blocked without that reason,
    so the judged party does not switch a required check off by a comment. A finding that
    blocked stops blocking only as fixed or with the judge's reason: carried by a finding
    that does not block, it needs one too, and the comment says that it blocked before and
    why it no longer does. The comment lists
    them under the new findings and says of each new finding whether its file changed since
    the head judged before; where GitHub no longer serves that head whole, it says the file
    was not compared, since that head could not be read, and never guesses. Only a file the
    comparison covers is marked, a changed one or a file the head's tree holds; a finding
    that names no file, or a path of neither tree such as the review's own material under
    `.review/`, carries no mark, and `earlier.json` says nothing of its change. A first run,
    and one that finds no comment of the check, or one written before this or whose hidden
    line does not read, judges as a first run and lists nothing; the job summary names the
    run before, or says that no run before was found, or that its comment does not read, and
    that the run judges as a first run. No permission, secret or input is added, so a caller
    changes nothing. Where the head that the run before judged lies on the first-parent line of
    the new head, the run builds on it and judges only the commits after it (below). Whatever
    commit the run builds on, each finding of the run before gets its state, so a finding that
    blocked never leaves the comment unsaid.
  - **What a run builds on**: before it writes its range, a run looks along the first parents
    of the head, from the head down to where its range starts, the last release tag on a release
    pull request or the merge base on any other, for the newest commit that a run judged, and
    judges only what came after it. A commit counts as judged where its check `range / range`
    passed or failed and the comment of that run, whose hidden line names the commit, stands on
    the pull request whose merge made it, with the same verdict; on a pull request, the head
    that its own run before judged counts too where it lies on that line, and the newer of the
    two counts. A skipped check counts for nothing, and so does a check whose comment is missing
    or names another commit, since a failed check also stands for no verdict and for a step that
    failed before the review, and a run that ends green with no model call posts no comment.
    The run judges the commits after the commit, and the description and the checks as on every
    run, and each finding of that run, ready or not, gets its state, as after a run before, with
    the opener's decisions on this pull request, so a ready run's findings stay in the comment.
    The pull request's own run before keeps its states where it is another run, on the very
    head, off the line or below the commit built on: both runs' findings get their states, each
    finding once, and the comment lists each run's findings under the commit it judged. What a
    run builds on decides the range it judges, never whether an earlier finding gets its state.
    Where no commit of the line was judged, the run judges the whole range as before. A head
    that does not descend from a judged commit by its first parents, as on a branch cut before
    it or after a rewritten history, builds on none for that commit, and a run on the very head
    that the run before judged never builds on that head. The reads take at most 30 seconds a call, 120
    seconds together and 100 commits of the line, with the workflow's token and its
    `checks: read`; where one fails or runs out, the run builds on none, judges the whole range
    and says in its job summary that it could not read the runs before, so a failed read never
    fails a review and the run never builds on a commit it could not verify. The first message
    tells the judge which case it is in and names the commit, and that nothing up to it is
    judged again; a run that builds on none gets the instructions and the first message it got
    before. The job summary says which of the three the run did, and the comment says it on its
    line `Built on:` after `Judged:`, naming the run and the commit it built on.
  - **The quote** (https://github.com/xippios/.github/issues/116): a finding blocks only where
    it quotes the sentence of the document that the change breaks. Each finding carries that
    sentence word for word in `quote`, and a blocking finding needs it. The script checks it
    against the text of the document that the finding names by its label, as the review read
    that document, every run of white space as one space and nothing else altered. A
    blocking finding that quotes nothing, whose quote that document does not hold, or that
    names no document of the review is answered once as a malformed verdict is, naming the
    finding and why, and the model calls again. Where the verdict that follows still holds
    such a finding, the finding stays in the comment as one that does not block, with one
    line under it that says its quote was not found, and where no finding blocks then, the
    verdict is `ready`. So a case that the wording of the documents leaves open does not
    block, on every pull request alike. The comment shows the quote under its finding, so a
    reader sees the rule that blocks, and the hidden last line carries it. A finding given
    before the quote has none: its hidden line reads as before, and a finding of the run
    before keeps the standing it was given with, so one that blocked stops blocking only as
    fixed or with the judge's reason. Two findings of the runs before are one where every
    field agrees, the quote included.
  - **A placed finding** (https://github.com/xippios/.github/issues/117): a finding against
    a rule that a document states as one blocks wherever a decision on the pull request
    placed it. A decision of the opener that places it in a later package or patch does not
    stop it from blocking, and the judge's instructions say so. Of a finding of the run
    before that blocked, a decision settles nothing by itself, as the run before says.
  - **The line** (https://github.com/xippios/.github/issues/85): a finding names a line only
    where its file has that line at the head, counted as `read_file` counts lines; where it
    has not, as in a file the head lacks or one the tools refuse, the finding keeps its file
    and names no line.
  - **What the model may do**: nothing but read. Before it starts, `conventions.py
    prepare` empties `.review/`, so nothing the pull request carries there survives, and writes
    its material there: `diff.patch` and `log.txt` of the range,
    `pr.json` (title, body, author, comments, files), `checks.json` (the head's checks, `ci`
    among them), `meta.json` (the coordinates and the range), the documents under
    `documents/`, listed in `documents.json`, and after a run before, `earlier.json` and
    `changed.json` (the run before, above). The system prompt carries the instructions and
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
    result, the prompt or an upstream's message, and `conventions.py verdict` redacts
    anything that looks like a key or a GitHub token from the summary and the comment.
- **`.github/workflows/conventions-range.yml`**, the conventions review of a range of commits,
  judges the commits since the last release once a merge completes a package, check
  `range / range`, after its gate tells whether a merge does, check `range / gate`. It runs on
  a push to `main` and on a dispatch, the events of the trigger file `conventions.yml` that are
  no pull request's (the trigger files, under the wiring below). The calling file hands over
  the secrets `ANTHROPIC_API_KEY` and `DOCUMENTS_READ_TOKEN`, both optional, as to
  `conventions.yml`, and no input. Permissions: `contents: read`, `pull-requests: write`,
  `checks: read`, `issues: read`. The variable `WORKFLOW_CONVENTIONS` switches it (the switch,
  under the wiring below).

  A trigger file grants these permissions from its start, since a caller that grants less than
  a called workflow asks for fails at its start.
  - **The gate** (`conventions.py range-gate`): the job `gate` runs on a push and on a dispatch
    alone, by its own condition, and needs no key and makes no model call. It checks the script
    out as `conventions.yml` does and runs it on the runner's `python3` with `-I`, on the
    standard library and `gh`, with the workflow's token, which the job narrows to
    `contents: read`, `pull-requests: read` and `issues: read`. The job times out after 5
    minutes. It writes `run`, `true` where the range is to be judged, and `pr`, the number of
    the pull request whose merge made the commit or nothing, to its outputs, and one sentence
    of what it decided and why to the log and the job summary. `run` is written last, after
    the sentence and `pr`, so an error after the decision fails the job and never leaves it
    `true`.
  - **A dispatch** always lets the range be judged, on any branch, and `pr` names the pull
    request whose merge made the commit where there is one.
  - **A push** is judged where the merge that made it completes a package, read in this order.
    A push to a branch other than the default branch is not judged. The pull request is the
    merged one among the commit's pull requests whose merge commit is the pushed commit, and
    a push without one is not judged. A release pull request, labeled `release` or titled
    `<version> Release`, is not judged, since its own review judged it, and neither is a pull
    request without a milestone. Then the gate reads the open issues of the milestone, keeps
    its steps and takes out those that the pull request closes: a step left holds the range,
    and the sentence names it; with none left, or none open at all, the range is judged.
  - **A step** is an open issue of the milestone whose type is `step`, compared without case.
    An issue that carries no type is a step where its title has the step form of a coordinate
    repository's issues, a version, the word `Step`, a number or a number and one follow-up
    number such as `3.1`, and a colon, so a package never looks complete because the types
    could not be read.
  - **The closing issues**: GitHub closes the issues that a merged pull request closes seconds
    after the merge, so a step that the pull request closes counts as closed though the answer
    still shows it open, and the gate waits for nothing. Only the closing issues of the calling
    repository count, and the gate reads every page of them.
  - **The reads**: the open issues are read from the milestone itself, page by page, never by
    a search, whose index can lag just after a merge. A call of `gh` gets at most 30 seconds
    and all of them together 240 seconds, so the gate ends with its line a minute before the
    job's timeout, and each read stops at its fiftieth page. An error fails closed: a call of
    `gh` that fails, does not run or does not come back in its time, an answer that does not
    parse or one of another shape, a GraphQL answer with errors and a read past its fiftieth
    page end the job red with a line that names the call and the class of the error, never
    its message, and `run` is never `true` then.
  - **The range** (`conventions.py range-prepare`): the job `range` needs the job `gate` and
    runs where the gate wrote `run` as `true`. It judges the commits since the last release tag
    (`v*`) reachable from the commit of the event, with the judge, the effort, the turn cap and
    the documents of the review of a release pull request, read as that review reads them: the
    README's `## Documents` on the default branch, another repository's document at the release
    that the commit's requirement admits, and the read token for a private caller alone. It
    judges no pull request: its material holds no description and no checks and names no
    release version, and the judge is told so, and that the release's own changes, the
    version's bump, the changelog's section and the tag, come with the release pull request, so
    their absence is no finding. Where no release tag is reachable from the commit, the run
    judges what the commit of the event changed against its first parent, which for a merge is
    the merged pull request's whole change, as the review of a release pull request without a
    tag judges the pull request's own diff (https://github.com/xippios/.github/issues/138). So
    before a repository's first release, a step that merged before the merge a run judges is
    judged by no run until the first tag exists. A commit with no parent is judged on its own
    change, and the job summary says which. A commit that carries the last release tag holds no commit after it: the job passes with its
    notice, makes no model call and posts no comment. A README that links no documents passes
    with its notice and makes no model call, as for a pull request.
  - **What a run builds on**: a run on a range builds on the newest commit of its line after the
    tag that a run on a range judged, as the review of a pull request does (above): it judges the
    commits after that commit, and it gives each of its findings its state, fixed or open,
    whatever that run's verdict, since a range has no opener whose decision settles one. A commit
    counts as judged where its check `range / range` passed or failed and its run's comment, which
    names it in its hidden line, stands on the pull request whose merge made it with the same
    verdict; a skipped check, a missing comment, a comment of another commit, and the two cases
    of a passed check without a model call, which post no comment, count for nothing. Where no
    release tag is reachable, the run judges the commit's change against its first parent and
    builds on none. The reads, their limits and a read that fails are as for a pull request,
    and the job summary and the comment say what the run built on.
  - **The check** `range / range` on the commit of the event is in one of three states.
    passed: the range was judged `ready`, or nothing was there to judge, a README that links no
    documents, or a commit that carries the last release tag, each with its notice and no model
    call; failed: the range was judged `not ready`, the review returned no verdict, or a step
    failed before it, the step `Key` without a key among them; skipped: the job reports as
    skipped where the gate did not let the range be judged or failed, and no runner starts for
    it. So a check that passed stands for a judged range but in those two cases.
  - **The verdict** (`conventions.py range-verdict`) goes to the job summary and, in the form
    of the check's comment on a pull request with its hidden last line, whose head is the judged
    commit, to one comment on the pull request whose merge made the commit, the gate's `pr`. A
    second run on the same commit rewrites that comment, which it finds by its hidden line, and
    the comment of the pull request's own review, which names its head, is never rewritten. A
    finding that names no file concerns the range. Where the gate names no pull request, as on
    a dispatch on a commit that no merge made, the job summary alone carries the verdict, and so
    where that pull request is a release pull request, which only a dispatch can bring, since
    it carries the comment of its own review. A read or a post that fails leaves its reason in
    the job summary and a warning annotation, as for a pull request.
  - **The quote** (https://github.com/xippios/.github/issues/116): a finding of a range blocks
    only where it quotes the sentence of the document that the change breaks, and the script
    checks the quote, asks once more and keeps a finding without it as one that does not
    block, as for a pull request, by the same code. A range has no pull request, so no
    decision places a finding of it.
  - **The key**: where `ANTHROPIC_API_KEY` is empty, the step `Key`, `conventions.py range-key`,
    fails the job with the Gate's sentence before the commit is checked out. The keys of
    several lines, the failover, the redaction, the public log and the line of an API error,
    its class and the request's id, hold as for a pull request, by the same code.
  - **The job** narrows the workflow token to `contents: read`, `pull-requests: write` and
    `checks: read`, the last for the runs before it builds on, times out after 45 minutes as the
    review of a pull request does, and runs in a concurrency
    group of its repository and ref, in which a newer run cancels the older one. It checks the
    script out and runs the step `Key`, then checks the commit out with its full history and no
    credential kept, which empties the workspace, then the script again, uv, and one call each
    of `range-prepare`, `review` and `range-verdict`, the values in `env:` blocks. Prepare
    refuses a link in place of `.sdk-gates` before the script runs from there.
  - **What a caller needs**: the trigger file `conventions.yml` with its job `range` and the
    permissions it grants, the secret `ANTHROPIC_API_KEY`, release tags `v` and a version on
    the commits a release ships, and a merge commit of each step's pull request on the default
    branch, which the gate reads. Without the key the check fails.
- **`.github/workflows/site-tests.yml`** runs a site's suite through the host xippios-web, the
  only test harness of the web platform, check `tests / tests`. It runs on a pull request and
  on a push to `main`, the events of the `ci.yml` that web-template renders into a site, which
  calls it as the job `tests`. The calling file hands over the input `site`, the site's key,
  and the secret `WEB_READ_TOKEN`, the organization's token that reads xippios-web and the sites
  it requires, both required. Permissions: `contents: read`. No variable switches it.

  A site's caller:

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
    Then it runs `php artisan dusk --testsuite=<site>` with the runner's Chrome and its driver
    against the host served by `php artisan serve` at `APP_URL` `http://127.0.0.1:8000`,
    Laravel's recipe for Dusk on GitHub Actions. Where the site has no `tests/Browser`, no npm
    runs and a notice says that Dusk does not run. The suites are the host's, one per site in its
    `phpunit.xml` and `phpunit.dusk.xml`, from xippios-web 0.1.0.
  - **The checks before**: an empty secret fails the check and names it. A pull request from a
    fork never gets the secret, so it fails there. A key that web-template's `copier.yml` would
    refuse fails, and so does a site whose `composer.json` names another package than
    `xippios/web-<site>`.
  - **The token** reaches two steps only: the host's checkout, which keeps no credential, and
    Composer's resolution, which gets the token in `COMPOSER_AUTH`, never on disk, and runs
    with `--no-scripts`, since the host's scripts boot the application, which runs the site's
    code, and `--no-plugins`, since a plugin the host allows runs inside Composer. The skipped
    scripts, package discovery among them, the plugins the host allows, the suite, the build and
    Dusk run after it, without the token. The build needs none: the host's `package-lock.json`
    takes every package from the public npm registry, and its `.npmrc` names no registry and no
    credential.

  PHP 8.4 and Composer 2.11.1 come from setup-php, and Node 22, the version the host's own
  `ci.yml` builds with, from setup-node, with no cache. The job times out after 20 minutes.
- **`.github/workflows/adr-index.yml`** checks that a repository's index of its architecture
  decision records is current, check `adr-index / adr-index`: `docs/adr.md` and `docs/adr.json`
  must be what the repository's own `scripts/adr_index.py` writes from the records in
  `docs/adr/`, and no two records may take one number. It runs on a pull request's opening,
  push and reopening, as its trigger file starts it. The calling file hands over no input and
  no secret. Permissions: `contents: read`. The variable `WORKFLOW_ADR_INDEX` switches it (the
  switch, under the wiring below).

  A `gates.yml` calls it as a job:

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
    `python3 -I scripts/adr_index.py`, which writes both files from the records, to be run and
    its files committed once what comes first is mended. After a failed `--check` that is any record
    the script's own lines above the annotation name, such as one whose first line does not
    read, since the script writes neither file while a record does not read; after a number
    twice, one of the two records renumbered. A record's name reaches an annotation escaped, so
    no name starts a workflow command.

  The checkout keeps no token, and the job times out after 5 minutes.
- **`.github/workflows/ci.yml`** checks this repository itself, check `ci`: ruff, the scripts'
  tests, actionlint and the spelling of `README.md`, `.github` and `scripts`. It runs on every
  pull request of this repository and on a push to `main`. No file calls it, since it is no
  reusable workflow. Permissions: `contents: read`. No variable switches it.

  The job `ci` runs ruff 0.17.1, the rev of the templates' `ruff-pre-commit` hook, the scripts'
  tests on a pinned pytest (with the review's `anthropic` 2.3.0 and `spelling.yml`'s codespell;
  a fake client, no key, no network), and actionlint with the runner's shellcheck on every
  `run:` script, and times out after 15 minutes. It calls `spelling.yml` over `README.md`,
  `.github` and `scripts` as the job `spelling`, and `ci` runs where that job failed too and
  fails at its last step where it did not pass, since a job that a failed need skips reports
  as skipped, which passes: so `ci` passes only where both pass. `ci` counts a `spelling` job
  that did not run as not passed, so the switch `WORKFLOW_SPELLING` is for callers. The one test of
  `site-tests.yml` that requires a site with the real Composer uses the runner's PHP and
  Composer, and is skipped elsewhere without them.

Every action in the workflows is pinned to a commit SHA with its version in a comment, written as
the action's own tags write it, with or without the `v`. It is the one comment a workflow file of
this repository carries: what a workflow does, and why, stands in this README. `setup-uv` installs
a pinned uv and `setup-php` a pinned Composer, the review runs a pinned `anthropic`, and the
spelling check a pinned codespell.

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
change of the title or of the base arrives as `edited`. An edit starts the review only, so the
trigger files `spelling.yml` and `adr-index.yml` below run on the first three types and the
trigger file `conventions.yml` on all four. A caller runs on no label (C57):
GitHub starts a workflow on a label of any name and reports a head's checks from its newest
run, so the run of a label could stand for the head. A label set
after the opening, `release` among them, counts from the next push or edit. The jobs of a
`gates.yml` or an `organization.yml` carry no `if:`, so each run reports every check: the
review's job decides in its own condition, under `conventions.yml` above, and its check reports
skipped and passing on a pull request that condition skips
(https://github.com/xippios/.github/issues/47).

| Workflow | Caller job | Check context |
| --- | --- | --- |
| `spelling.yml` | `spelling` | `spelling / spelling` |
| `conventions.yml` | `conventions` | `conventions / conventions` |
| `conventions-range.yml` | `range` | `range / range` |
| `conventions-range.yml` | `range` | `range / gate` |
| `adr-index.yml` | `adr-index` | `adr-index / adr-index` |
| `site-tests.yml` | `tests` | `tests / tests` |

A context joins the caller's job id and the callee's job name, so a required check names the
slash-joined context and a caller keeps the job ids above. The caller passes the review its
secrets by name, never `secrets: inherit`: `ANTHROPIC_API_KEY`, and `DOCUMENTS_READ_TOKEN`,
which the review needs only in a private repository whose README lists a private repository's
document (the read token under `conventions.yml` above). A trigger file passes both, and a
repository without the read token passes the empty string, which reads as none. A caller grants
the permissions the workflow it calls asks for; a caller that grants less fails at the start.

### The trigger files

A repository takes part in a check by one small workflow file of its own, its trigger file,
named as the central workflow of its check (https://github.com/xippios/.github/issues/102,
https://github.com/xippios/.github/issues/107). It names the events, the permissions and the
secrets and calls this repository at `main`, so the logic stays here and a change of it reaches
every caller with its merge. The presence of a trigger file switches its check on. Where a
repository requires a check, the requirement goes before the file does. A `gates.yml` and an
`organization.yml` call the workflows as before until their repository takes the trigger files
with an adoption, and both wirings report the check contexts of the table above.

The trigger file `conventions.yml` runs on a pull request's four types, on a push to `main` and
on a dispatch. Its job `conventions` calls `conventions.yml` on a pull request, and its job
`range` calls `conventions-range.yml` on every other event. Each job carries one condition, the
name of the event and the switch `WORKFLOW_CONVENTIONS`, which is on unless the variable is
`off`: GitHub reads the repository's variable over the organization's and compares without
case. So a pull request shows one skipped `range`, a push or a dispatch one skipped
`conventions`, and on `off` neither job calls its workflow. Both jobs pass `ANTHROPIC_API_KEY`
and `DOCUMENTS_READ_TOKEN` by name. A repository's `.github/workflows/conventions.yml`:

```yaml
name: Conventions

on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  conventions:
    if: github.event_name == 'pull_request' && vars.WORKFLOW_CONVENTIONS != 'off'
    uses: xippios/.github/.github/workflows/conventions.yml@main
    permissions:
      contents: read
      pull-requests: write
      checks: read
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      DOCUMENTS_READ_TOKEN: ${{ secrets.DOCUMENTS_READ_TOKEN }}

  range:
    if: github.event_name != 'pull_request' && vars.WORKFLOW_CONVENTIONS != 'off'
    uses: xippios/.github/.github/workflows/conventions-range.yml@main
    permissions:
      contents: read
      pull-requests: write
      checks: read
      issues: read
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      DOCUMENTS_READ_TOKEN: ${{ secrets.DOCUMENTS_READ_TOKEN }}
```

The trigger files `spelling.yml` and `adr-index.yml` run on a pull request's opening, push and
reopening, the types `opened`, `synchronize` and `reopened`, since an edit starts the review
only. Each has its one job under the job id that keeps its check context and carries no
condition, since the workflow it calls carries its switch (the switch, below). A root's
`.github/workflows/spelling.yml`:

```yaml
name: Spelling

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read

jobs:
  spelling:
    uses: xippios/.github/.github/workflows/spelling.yml@main
    with:
      paths: rules docs/style docs/adr docs/adr.md docs/adr.json docs/reports README.md CLAUDE.md .claude workspace.toml labels.yml
```

A repository's `.github/workflows/adr-index.yml`:

```yaml
name: ADR index

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read

jobs:
  adr-index:
    uses: xippios/.github/.github/workflows/adr-index.yml@main
```

### The switch

A variable `WORKFLOW_<NAME>` with the values `on` and `off` switches a workflow whose file
exists (https://github.com/xippios/.github/issues/111): GitHub reads the calling repository's
variable over the organization's, a called workflow reads its caller's, and the workflow is on
where neither sets one. Only `off` switches it off, compared without case, and any other value
leaves it on. `spelling.yml` and `adr-index.yml` carry their switch in their job's condition,
`vars.WORKFLOW_SPELLING != 'off'` and `vars.WORKFLOW_ADR_INDEX != 'off'`, so on `off` no runner
starts and the check reports as skipped and passing. The review carries its switch
`WORKFLOW_CONVENTIONS` in the trigger file `conventions.yml` above, so on `off` neither of its
jobs calls a workflow and `conventions / conventions` reports nothing.

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
names another ref) and a pull request labeled `release` or titled `<version> Release` on its
release's range, with its version, and runs the review, then
prints the summary line and the findings, each with the document it goes
against. A README that links no documents ends it there, green, as in the workflow. It reads
the run before from the check's last comment as the workflow does, since that comment is the
workflow token's whatever `gh`'s login, and posts nothing. `--earlier <file>` takes the verdict
file that an earlier dry run wrote with `--out`, which names the pull request and the head
that run judged, and stands for the check's comment, so a dry run judges as a later run before
any comment carries the hidden line. It refuses, before any clone, the file of a run that
returned no verdict and that of another pull request. It prints the states and the marks as the comment shows them, after the
findings. Both forms below look for the judged commit to build on as the workflow does: each
reads the runs before with gh's login and prints which judged commit it builds on, or that it
builds on none and why, before the review starts. It needs
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

`--commit <sha>` in place of `--pr <n>`, a full commit SHA, clones the repository at that
commit and judges its range as the job `range` does: from the last release tag reachable from
it, or, where none is, what the commit changed against its first parent, with no pull request,
no description and no checks.
It prints the summary line and the findings, posts nothing and takes no `--earlier`. No workflow
can call a changed job `range` before its merge, so this is how a change of it is seen first:

```sh
read -rs K && ANTHROPIC_API_KEY="$K" uv run --no-project \
  --exclude-newer 2026-10-29T00:00:00Z --with anthropic==2.3.0 \
  python <this clone>/scripts/conventions.py dry-run --repo xippios/<repo> --commit <sha>
unset K
```

`--model`, `--effort` and `--max-turns` change the judge, its effort and the turn cap;
`--out` also writes the verdict file. Exit status: 0 `ready`, 1 `not ready`, 2 no
verdict.

## Changing this repository

A change here is a branch and a pull request, which `ci` checks (the checks, above). A pull
request that changes `conventions.py` is checked by `ci` and the dry run above; the review no
longer runs on this repository's own pull requests (C58). The documents the review judges by
are each repository's own, listed in its README's `## Documents` (C80), so nothing here decides
what a repository is held to.
