"""The enums of qa.json, and how each value is shown."""
VERDICTS = {"passed": "✅ Passed", "passed_with_caveats": "✅ Passed with caveats", "failed": "❌ Failed",
            "blocked": "⛔ Blocked"}
RESULTS = {"passed": "✅ Passed", "failed": "❌ Failed", "blocked": "⛔ Blocked", "not_run": "⏭ Not run"}
AS_EXPECTED = {"yes": "Yes", "no": "No", "partial": "Partly", "n/a": "N/A"}
TYPES = {"success": "Success", "valid": "Valid", "invalid": "Invalid", "validation": "Validation", "failure": "Failure",
         "edge_case": "Edge case", "boundary": "Boundary", "security": "Security", "permission": "Permission",
         "concurrency": "Concurrency", "integration": "Integration", "regression": "Regression", "ui": "UI",
         "performance": "Performance"}
NEGATIVE_TYPES = ("invalid", "validation", "failure", "edge_case", "boundary", "security", "permission", "concurrency")
LEVELS = {"e2e_ui": "E2E (browser → API → DB)", "e2e_api": "E2E (API request → DB)", "functional": "Functional",
          "unit": "Unit", "data": "Data / migration", "manual": "Manual steps"}
EVIDENCE = ("executed", "existing_test", "static")
ENVIRONMENTS = ("test", "development", "local_server")
STEP_RESULTS = ("passed", "failed", "blocked", "info")
ROLES = ("entry", "ui", "middleware", "auth", "validation", "controller", "service", "model", "db", "callback", "job",
         "mailer", "external", "event", "response", "other")
SEVERITIES = ("critical", "major", "minor", "info")
REQ_SOURCES = ("ticket", "code", "inferred", "user")
REQ_STATUS = {"met": "✅ Met", "not_met": "❌ Not met", "partial": "◐ Partly met", "untested": "⏭ Not tested"}


def as_expected(sc):
    """The scenario's "Expected?" value: given, or derived from its result."""
    v = sc.get("as_expected")
    if v in AS_EXPECTED:
        return v
    return {"passed": "yes", "failed": "no"}.get(sc.get("result"), "n/a")


def requirement_status(req, scenarios):
    if req.get("status") in REQ_STATUS:
        return req["status"]
    res = [s.get("result") for s in scenarios if req["id"] in (s.get("requirements") or [])]
    ran = [r for r in res if r in ("passed", "failed")]
    if not ran:
        return "untested"
    if all(r == "passed" for r in ran):
        return "met" if len(ran) == len(res) else "partial"
    return "not_met" if all(r == "failed" for r in ran) else "partial"
