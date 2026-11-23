# Changelog

## 1.0.0

- `/qa`: QA the current branch against a ticket given inline (on the lines after `/qa`), as a file, URL or issue id, or with no ticket (expected behaviour inferred and flagged).
- `prepare.py`: branch diff vs auto-detected base (uncommitted work included), changed symbols, impact map (layer, signals, routes, entry points, callers, covering tests), suggested test level per area, test runners, E2E tools, dev servers, tracers.
- `ticket.py`: acceptance criteria, checklists and Given/When/Then → requirements.
- `run_tests.py` (runner output + JUnit), `http_check.py` (localhost API E2E with assertions, cookies, saved values), `ui_check.py` (headless browser E2E with form → API request checks, console errors, screenshots).
- `trace_py.py` / `trace_rb.rb` runtime tracers with a per-scenario code path; outbound network blocked.
- `render.py`: validates qa.json; interactive report (results, requirements coverage, impact, findings, copy for the ticket as Markdown / Jira / plain / rich table); chat summary table.
