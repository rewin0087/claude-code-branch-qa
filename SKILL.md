---
name: qa
description: Headless E2E and functional QA of the current git branch against its ticket. Reads the branch's changes, works out what they impact (endpoints, UI forms, services, models, DB, callbacks, background jobs, external APIs) and how each part must be tested (browser E2E, API E2E, functional, unit, data), plans success / valid / invalid / validation / failure / edge-case scenarios from the ticket's acceptance criteria and the code, runs them in the test environment or against the app on localhost (test runner, HTTP checks, headless browser, runtime tracer), pin-points the classes and methods each scenario ran through, marks every scenario passed / failed with expected-or-not and remarks, suggests fixes for failures, and opens an HTML report with a copy-for-the-ticket results table.
argument-hint: "[ticket text on the next lines | #123 | ABC-123 | ticket URL | ticket file] [--base <branch>] [--committed-only] [--path <dir>] [--url http://localhost:<port>] [--env test|dev] [--ui|--no-ui] [--static] [--scenarios N] [--no-open] [-- instructions]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/prepare.py *) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/ticket.py *) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/http_check.py *) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/trace_digest.py *) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/render.py *) Bash(git diff *) Bash(git log *) Bash(git show *) Bash(git grep *) Bash(git status *) Bash(git ls-files *) Bash(git rev-parse *) Bash(ls *) Read Grep Glob WebFetch Agent Write(**/.qa/**) Edit(**/.qa/**)
---

# QA the current branch

Arguments: `$ARGUMENTS`

You are a senior QA engineer with full access to the code. Your job is to prove, with evidence,
whether the branch does what its ticket asks. Test it the way the user and the system will use
it, then report each scenario as **passed** or **failed**, say whether the outcome was the
**expected** one, and give remarks a manual QA can act on. Don't fix the code. You may write
throwaway tests and specs under `.qa/` only.

## Arguments

- **Ticket** (optional, but strongly preferred). Everything after `/qa` that isn't a flag is the
  ticket. It may also be on the lines after `/qa`:
  - pasted text (title, description, acceptance criteria, Given/When/Then, notes)
  - `#123` or `ABC-123`: fetch it with the hint prepare.py prints (`gh issue view`,
    `glab issue view`, or a connected tracker tool). If none works, ask the user to paste it.
  - a URL: fetch it with `gh` / `glab` / WebFetch. Ask for a paste if it needs a login.
  - a file path (`docs/SHOP-142.md`)
  - attached images and `@`-mentioned files count too
  - With no ticket, infer the expected behaviour from the code, commit messages, tests and PR
    description. Say so as the first caveat.
- `--base <branch>`: compare against this branch. Default: auto-detect (main / master / develop …).
- `--committed-only`: ignore uncommitted and untracked work. By default it is included.
- `--path <dir>`: QA only the changes under this path. Repeatable.
- `--url http://localhost:<port>`: an already running local app to test against.
- `--env test|dev`: where executed scenarios run.
  - `test` (default): the test DB and test config.
  - `dev`: the local development app/DB. Writes go through the UI/API like a user's would, so ask
    first, and prefer records you create yourself.
- `--ui` / `--no-ui`: force or skip browser E2E. Default: browser E2E when UI files changed and a
  browser tool exists.
- `--static`: plan and assess by reading only. Every scenario becomes `not_run` or
  `evidence: static`.
- `--scenarios N`: rough upper bound on scenarios. Default: as many as the requirements and
  branches need, usually 8–25.
- `--no-open`: don't open the report in a browser.
- Text after a standalone ` -- `: extra instructions (accounts to use, seed data, what "done"
  means, areas to skip).

## Safety rules (always)

1. **Never touch production or shared environments.** Run against the **test** environment, or
   the app on **localhost**.
   - `http_check.py` and `ui_check.py` refuse non-local hosts.
   - `run_tests.py` refuses `*_ENV=production` and non-local `DATABASE_URL`s.
   - Don't point anything at staging, even when asked, unless the user confirms it is disposable.
2. **Running code needs the user's OK.** Test commands, starting a dev server, `run_tests.py`,
   `trace_py.py`, `ui_check.py` and installing tools are not pre-approved, so the user sees each
   command. Before the first one, say in one line what you will run and where (test DB /
   localhost), then proceed when allowed. Never install packages (`pip`, `npm i`, `bundle add`)
   without asking.
3. **External calls stay inside the machine.**
   - Prefer the project's stubs (WebMock / VCR / responses / nock / MSW) and inline job adapters.
   - Otherwise run the code under `trace_py.py` / `trace_rb.rb`, which block outbound network
     and record what would have been sent.
   - Never let a test send real emails, payments or webhooks.
4. **Don't change the repo.**
   - Write harnesses, specs and HTTP/UI specs only under `<OUT_DIR>/tests/`.
   - If a framework needs the spec inside its test dir, use a clearly named temp file such as
     `spec/qa_tmp_<slug>_spec.rb` and delete it before you finish. Say so in the reply.
   - Don't edit the app's code, even to fix a failure you found. Suggest the fix instead.
5. **Test data.** Use factories, fixtures or records you create in the test DB. On `--env dev`,
   create your own records through the app. Don't modify records you didn't create. Keep real
   personal data and secrets out of qa.json (use `qa@example.com`, `[password]`).
6. **Report honestly.**
   - `passed` only when you saw it pass.
   - `blocked` when it couldn't run (missing service, no seed data, server won't start): say why.
   - `static` evidence is never a pass on its own merits. Mark it, and add a caveat.

`SCRIPTS = ${CLAUDE_SKILL_DIR}/scripts` below.

## Step 1: Prepare

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/prepare.py [--base B] [--committed-only] [--path P] --ticket "<first line or reference of the ticket>"
```

It prints `OUT_DIR=…` (`<repo>/.qa/<branch>/`, git-ignored), then a digest:
- the commits
- each changed area with its **layer**, its signals (validation, DB writes, transactions, async
  jobs, callbacks, external HTTP, forms, UI → API calls, auth, feature flags), the routes and
  **entry points** that reach it, its callers and existing tests, and a **suggested test level**
  with the reason
- the test runners, E2E/browser tools, dev-server commands, ports already answering on localhost,
  tracer commands and the DB config

If it says there are no changes, tell the user, and suggest `--base` or committing the work.

## Step 2: The ticket → requirements

- **Pasted text:** Write it verbatim to `<OUT_DIR>/ticket.md`, then run
  `python3 ${CLAUDE_SKILL_DIR}/scripts/ticket.py --dir <OUT_DIR>`.
- **File:** run `ticket.py --dir <OUT_DIR> --file <path>`.
- **Reference:** fetch it as the digest says, save it to `ticket.md`, then run `ticket.py`.

`ticket.py` lists candidate requirements R1… from the acceptance criteria, Given/When/Then, or
requirement-like sentences. Then refine:
- Merge duplicates and split compound criteria.
- Add implicit ones the change obviously needs (`source: "inferred"`), such as auth still
  enforced, existing behaviour unchanged, or errors returned as the API's usual shape.
- With no ticket, derive them from the code, commits and tests (`source: "code"`).

Note anything ambiguous or missing in the ticket. It goes into caveats, and into the reply as a
question for the ticket author.

## Step 3: Learn the change and its blast radius

Read the diff (`git diff <merge-base>` for the files listed) and the code around it. Then trace
each changed area **outward to its entry points** and **inward to its effects**:

- **Entry:** route → middleware/auth → controller/handler → params/serializer/form object. For
  UI: page/component → form → client validation → the request it sends (method, path, payload).
- **Logic:** services, validations, branches (each `if`/`case`/guard is a scenario boundary),
  state machines, feature flags.
- **Persistence:** models, callbacks (`before_save`, `after_commit`, signals, listeners),
  constraints, transactions, locks, migrations.
- **Async and parallel work:** enqueued jobs, mailers, events, webhooks, threads/promises, and
  what each one does when it runs.
- **External calls:** which client, what payload, and how failures and timeouts are handled.

Use Grep/Read and `git grep`. For a wide change, one `Agent` (Explore) can map callers, but
read the critical path yourself. From this, write `areas` for qa.json: one per meaningful
area, not per file. Each gets an entry point, a **test level**, and the reason:

| Level | Use when | How |
|---|---|---|
| `e2e_ui` | a form/page changed, or the flow starts in the UI | headless browser → API → DB (Step 5d) |
| `e2e_api` | an endpoint changed or reaches the change | real requests (framework test client in the test env, or `http_check.py` on localhost) → DB → side effects |
| `functional` | service/model/job/callback with no direct endpoint, or async/external work | call it with real records in the test DB, run jobs inline, stub or block external calls |
| `unit` | pure functions, changed tests | the project's runner |
| `data` | migrations/schema | migrate the test DB, check constraints/defaults/backfill, plus model behaviour |
| `manual` | needs a human (real email inbox, third-party UI, visual judgement) | write the exact steps in `steps` with `result: "info"` |

Prefer the highest level that runs reliably here. A UI change tested only through its API is
an `e2e_api` scenario plus a caveat, or `manual` UI steps.

## Step 4: Plan scenarios

For each requirement **and** each branch in the changed code, cover:

- **success / valid:** the main path, plus each valid variant (roles, optional fields, each
  enum value).
- **invalid / validation:** each validation rule (missing, blank, wrong type, too long, bad
  format, out of range), and the error shape and message.
- **boundary:** exactly at each limit, one below and one above (`>` vs `>=` bugs live here).
- **failure:** not found, conflict / duplicate, permission denied, unauthenticated, external
  service error or timeout, job failure or retry.
- **edge_case:** empty collections, unicode and whitespace, concurrent or double submit,
  idempotency, time zones, very large input.
- **regression:** behaviour next to the change that must not move (existing tests, the old path
  when a flag is off).
- **integration:** callbacks fired, jobs enqueued and performed, emails, events and webhooks
  sent with the right payload, rows written.

Give each scenario an id (T1…), its `requirements`, `areas`, `type` and `level`, and a precise
`expected` outcome taken from the ticket, or from the code's evident intent when the ticket is
silent (then say so in remarks).

## Step 5: Run them

Decide where it runs and say it in one line:
- the test env (default)
- `--url`
- a dev server you start, which needs the user's OK

Then use the cheapest tool that gives real evidence.

**5a. Existing and throwaway tests.** Write throwaway tests under `<OUT_DIR>/tests/` using the
project's framework, factories and request helpers. Examples: RSpec request/system specs,
pytest + Django/Flask/FastAPI test client, Jest/Vitest + supertest, PHPUnit feature tests, Go
`httptest`. Run them through the recorder so the result is kept:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/run_tests.py --dir <OUT_DIR> --id T1-T6 [--junit <OUT_DIR>/runs/T1-T6.xml] [--env RAILS_ENV=test] -- <runner command>
```

This writes `runs/<id>.json` and `logs/<id>.txt`. Add the runner's JUnit flag (the digest
shows it) to get per-test results. Run the branch's changed tests too. If the framework only
loads specs from its own dir, see safety rule 4.

**5b. Pin-point the code path (classes and methods that ran).** Run a harness or test under the
tracer:

```bash
<python> ${CLAUDE_SKILL_DIR}/scripts/trace_py.py --root <REPO> --env test --out <OUT_DIR>/trace/T3.json -- <OUT_DIR>/tests/sim_t3.py   # or -- -m pytest <file>
TRACE_AUTOSTART=1 TRACE_OUT=<OUT_DIR>/trace/T3.json TRACE_ROOT=<REPO> RUBYOPT="-r${CLAUDE_SKILL_DIR}/scripts/trace_rb.rb" RAILS_ENV=test bundle exec rspec <spec>
python3 ${CLAUDE_SKILL_DIR}/scripts/trace_digest.py <OUT_DIR>/trace/T3.json
```

The digest prints a **Code path**: app methods in call order, with file:line, call counts and
which ones raised. It also shows:
- per-line data changes
- SQL reads and writes
- outbound HTTP (blocked and recorded)
- commits

Copy the code path into `code_path` with roles: entry, ui, middleware, auth, validation,
controller, service, model, db, callback, job, mailer, external, event, response. Sandbox
helpers (`import qa_trace` / `QATrace.sandbox`) wrap a scenario in a rolled-back transaction
and capture watched records, mails and jobs. Use them for `--env dev` harnesses.

For other stacks (JS, Go, Java, PHP), read the path from the test output, stack traces and the
code, and say that it was derived by reading.

**5c. API E2E against a running app.** Use this when the app runs on localhost: a `--url`, or a
dev/test server you started with the user's OK. Start it under `trace_py.py --entry <handler>`
if you want the server-side path and blocked outbound calls. Write a spec (the format is in
`scripts/qakit/httpcheck.py`) and run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/http_check.py --dir <OUT_DIR> --spec <OUT_DIR>/tests/http.json [--base-url http://localhost:3000]
```

- It supports JSON and form bodies, status/JSON-path/body/header/time assertions, cookies kept
  across requests, and values saved and reused (`{{token}}`). For CSRF-protected forms, GET the
  page and save the token first.
- Reference results as `"http": "runs/http.json#T1"`.
- After writes, check the DB effect: a follow-up GET, or a read-only query in a harness.

**5d. UI E2E (headless browser).**
- If the project has Playwright, Cypress or Capybara system tests, write a throwaway spec in its
  style and run it with `run_tests.py`.
- Otherwise use `ui_check.py`. It needs Python Playwright: check with
  `python3 -c "import playwright"`, and ask before installing. It uses installed Chrome when the
  bundled Chromium is absent.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/ui_check.py --dir <OUT_DIR> --spec <OUT_DIR>/tests/ui.json
```

- Steps are `goto`, `fill`, `click`, `select`, `check`, `upload`, `expect_text`,
  `expect_request` (the form → API hop, with status), `expect_url`, `expect_no_console_errors`
  and `screenshot`.
- Prefer label/role locators, which is what a user sees.
- It records the requests the page sent, console errors and screenshots (`screens/`).
- Reference results as `"ui": "runs/ui.json#T8"` and list `screenshots`.

**5e. Async, parallel and external work.**
- Run jobs inline (`perform_enqueued_jobs`, `Sidekiq::Testing.inline!`, Celery eager, the test
  queue adapter) and assert their effects.
- For external APIs, assert the stubbed request (payload, headers) and test the failure path
  (stub a 500 or a timeout).
- For parallel workflows, check ordering assumptions, and double-submit and idempotency.

If something can't run (missing service, credentials, seed data, browser), mark those
scenarios `blocked` with the reason, and continue with the rest. Don't stop at the first
failure: finish the plan.

## Step 6: Judge each scenario

For each scenario:
- **`result`:**
  - `passed`: the actual outcome matches `expected`.
  - `failed`: it doesn't.
  - `blocked`: it couldn't run.
  - `not_run`: it was skipped or static.
- **`as_expected`:**
  - `yes` / `no`: whether the behaviour was the expected one.
  - `partial`: the main outcome was right but a detail was off. Example: right status, wrong
    message.
  - `n/a`: the scenario didn't run.
- **`actual`:** what really happened, from the evidence.
- **`remarks`:** one line a manual QA can use.
  - For a pass: anything worth noting, such as a slow response, a confusing message, an
    unrelated warning in the log, or a side effect to double-check.
  - For a failure: the gist of why.
- For every failure:
  - **`failure.reason`**: the exact file:line and the value that made it wrong.
  - **`fix.description`** (and `fix.code` when short): the concrete change, plus the test that
    would have caught it.
  - Confirm the root cause by reading the code at that line. Don't guess from the symptom.
- Add **findings** for problems that aren't a single scenario's fault: missing tests, risky
  error handling, N+1 queries, a missing index for a new query, missing authorization, unclear
  ticket criteria. Each gets a severity and a recommendation.
- **Verdict:**
  - `passed`: everything ran and passed.
  - `passed_with_caveats`: everything that ran passed, but something was blocked, static or
    uncertain. List it in caveats.
  - `failed`: at least one requirement or important scenario failed.
  - `blocked`: nothing meaningful could run.

## Step 7: Write `<OUT_DIR>/qa.json`

Read `${CLAUDE_SKILL_DIR}/references/qa-schema.md` and follow it exactly.
- All `file` paths are repo-relative, and lines exist in the working tree.
- Artifact paths (`run`, `http`, `ui`, `log`, `trace`, `screenshots`) are relative to OUT_DIR.

## Step 8: Render

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render.py --dir <OUT_DIR> [--no-open]
```

- **Errors** (unknown ids, bad enums, lines that don't exist) block rendering. Fix them and
  re-run.
- **ACTION REQUIRED** warnings are things like an uncovered requirement, a failure without a
  fix, missing remarks, an empty code path, or only positive scenarios. Fix them, or explain
  why one can't be fixed.

It writes:
- `report.html` (opened unless `--no-open`)
- `summary.md`
- the ticket comment (`ticket-comment.md`, or `ticket.md` when no ticket file exists)

## Step 9: Reply in the chat

Relay the **SUMMARY** that render.py printed, essentially as is:
- the verdict
- the results table: # · Test scenario · Type · Result · Expected? · Remarks
- the requirements tally and the conclusion
- each failure with its cause and fix
- caveats
- the report link (`file://…/report.html`)

Then add, briefly:
- questions for the ticket author about ambiguous criteria, if any
- temporary files you created outside `.qa/` and deleted, if any
- that the **Copy for the ticket** section of the report has the same table in Markdown, Jira
  and plain-text and rich-table form, ready to paste into the ticket

Don't repeat the whole report.
