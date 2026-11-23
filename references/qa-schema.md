# qa.json schema

Write `<OUT_DIR>/qa.json`. `render.py` validates it.
- **Errors** block rendering: unknown ids, bad enums, missing required fields, files or lines
  that don't exist.
- **Warnings** are printed as ACTION REQUIRED: an uncovered requirement or area, a failure
  without a reason or fix, missing remarks, an empty code path, only positive scenarios, or a
  verdict that contradicts the results.

`file` values are **repo-relative**, and `line` / `end_line` are 1-based lines in the working
tree. Artifact paths (`run`, `http`, `ui`, `log`, `trace`, `screenshots`) are **relative to
OUT_DIR**. Text fields accept light markdown: `code`, **bold**, [links](https://…), `- ` lists.

```jsonc
{
  "title": "SHOP-142 Refund limits",                         // required
  "ticket": {"id": "SHOP-142", "title": "Refund limits", "url": "https://…", "source": "ticket.md"},
  "summary": {
    "verdict": "failed",              // required: passed | passed_with_caveats | failed | blocked
    "headline": "Full refunds are rejected (off-by-one in validate_amount)",   // required, one sentence
    "overview": "2–4 sentences: what the branch does, what you ran and where, what you found.",
    "conclusion": "The paragraph QA pastes on the ticket: ready or not, what fails, what to re-test.",
    "how_tested": "- markdown list: commands / tools / environment used",
    "stack": "Rails 7.1 · PostgreSQL · Sidekiq"
  },

  // What the ticket asks for, one testable statement each.
  "requirements": [
    {"id": "R1", "text": "Refund amount must be greater than 0",
     "source": "ticket",            // ticket | code (no ticket: read from the code) | inferred | user
     "status": "met"}               // optional; derived from its scenarios: met | not_met | partial | untested
  ],

  // The parts of the change, and how each was tested.
  "areas": [
    {"id": "A1", "name": "Refund API + validation", "layer": "endpoint",
     "files": ["app/services/refunds/create.rb"],
     "entry": {"file": "app/controllers/refunds_controller.rb", "line": 8, "symbol": "RefundsController#create"},
     "test_level": "e2e_api",       // e2e_ui | e2e_api | functional | unit | data | manual
     "reason": "Reached from POST /orders/:id/refunds: tested through real requests"}
  ],

  "environment": {"env": "test", "base_url": "http://localhost:3000", "db": "test DB (PostgreSQL, factories)",
                  "notes": "Sidekiq inline; Stripe stubbed with WebMock"},

  "scenarios": [{
    "id": "T1",                                     // required, unique
    "title": "Partial refund within the remaining amount",   // required: the table's "Test scenario"
    "type": "success",                              // required (the table's "Type")
    // success | valid | invalid | validation | failure | edge_case | boundary | security | permission |
    // concurrency | integration | regression | ui | performance
    "level": "e2e_api",                             // e2e_ui | e2e_api | functional | unit | data | manual
    "requirements": ["R4"], "areas": ["A1"], "findings": ["F1"],
    "result": "passed",                             // required: passed | failed | blocked | not_run
    "as_expected": "yes",                           // yes | no | partial | n/a (default: from result)
    "evidence": "executed",                         // executed | existing_test | static
    "environment": "test",                          // test | development | local_server
    "description": "Why this scenario matters",
    "preconditions": ["Order 4512: total 2000, refunded 1500"],
    "input": {"amount_cents": 200},
    "expected": "201, refunded 1700, status partially_refunded",   // warning if missing
    "actual": "201 {refunded_cents: 1700, status: partially_refunded}",

    // Step-by-step workflow (what a manual QA would do / what the test did).
    "steps": [
      {"action": "POST /api/orders/4512/refunds {amount_cents: 200}", "expected": "201", "actual": "201",
       "result": "passed",                          // passed | failed | blocked | info (manual steps)
       "file": "app/controllers/refunds_controller.rb", "line": 8, "symbol": "RefundsController#create"}
    ],

    // The classes / methods that ran to achieve it, in order (from trace_digest.py "Code path").
    "code_path": [
      {"symbol": "RefundsController#create", "file": "app/controllers/refunds_controller.rb", "line": 8, "role": "controller"},
      {"symbol": "Refunds::Create#call", "file": "app/services/refunds/create.rb", "line": 12, "role": "service"},
      {"symbol": "Refund after_commit → ReceiptJob", "file": "app/models/refund.rb", "line": 9, "role": "callback"}
      // role: entry | ui | middleware | auth | validation | controller | service | model | db | callback |
      //       job | mailer | external | event | response | other
    ],
    "side_effects": {"db": ["orders[4512].refunded_cents 1500 → 1700"], "jobs": ["ReceiptJob enqueued + performed"],
                     "emails": ["Receipt to ana@example.com"], "external": ["Stripe POST /v1/refunds (stubbed)"],
                     "events": ["refund.created"]},

    // Evidence (relative to OUT_DIR). `evidence: executed` needs at least one of run/http/ui/log/trace/command.
    "command": "bundle exec rspec .qa/…/tests/refunds_spec.rb:12",
    "run": "runs/T1-T6.json",                       // run_tests.py result
    "http": "runs/http.json#T1",                    // http_check.py result, by request id
    "ui": "runs/ui.json#T8",                        // ui_check.py result, by scenario id
    "log": "logs/T1-T6.txt", "trace": "trace/T1.json", "test_file": "tests/refunds_spec.rb",
    "screenshots": ["screens/T8-final.png"],

    "remarks": "One line for the results table: why it failed, or what QA should note",   // warning if missing

    // Required (as warnings) when result = failed:
    "failure": {"reason": "`validate_amount` uses `>=`, so the exact remaining amount is rejected",
                "file": "app/services/refunds/create.rb", "line": 19, "symbol": "validate_amount"},
    "fix": {"description": "Use `>` and add a boundary spec", "code": "if amount > remaining", "language": "ruby",
            "file": "app/services/refunds/create.rb", "line": 19}
  }],

  "findings": [{
    "id": "F1", "severity": "major",               // critical | major | minor | info
    "title": "Full refunds are impossible", "description": "…", "file": "…", "line": 19,
    "scenarios": ["T3", "T9"], "recommendation": "…", "code": "optional snippet"
  }],

  "caveats": ["No ticket was given: expected behaviour inferred from the code", "Concurrency not tested"],
  "remarks": ["Optional general notes for QA"],
  "not_covered": ["Admin UI (no access in the test env)"],
  "references": [{"title": "…", "url": "https://…", "note": "…"}]
}
```

## Rules

- **Coverage.** Every requirement and area has at least one scenario. Every branch in the
  changed code has a scenario on each side. Include invalid / validation / boundary / failure
  cases, not only the happy path.
- **Evidence.**
  - `passed` and `failed` come from something that ran: `evidence: executed` or
    `existing_test`.
  - Static judgements are `not_run`, or `static` with a caveat.
  - Values in `actual` come from the run output, never from what the code "should" do.
- **Remarks** are short and specific: a number, a message, a file:line.
- **Failures** name the line and the value that is wrong, and give a concrete fix with the test
  that would catch it.
- **Verdict** agrees with the results.
  - With any failure, it is `failed`.
  - When anything is blocked, static or uncertain, it is `passed_with_caveats`, with caveats.
- **No secrets or real personal data.** Use `qa@example.com`, `[password]`, `[token]`.
