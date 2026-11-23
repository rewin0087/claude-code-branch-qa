"""QAValidator: errors block rendering, warnings are printed as ACTION REQUIRED."""
import os

from . import vocabulary as V
from .sourcefile import SourceCache


class QAValidator(object):
    def __init__(self, qa, repo, out_dir):
        self.qa, self.repo, self.out_dir = qa, repo, out_dir
        self.sources = SourceCache(repo)
        self.errors, self.warnings = [], []

    def validate(self):
        qa = self.qa
        if not isinstance(qa, dict):
            return ["qa.json must be an object"], []
        if not qa.get("title"):
            self.errors.append("title is required")
        s = qa.get("summary") or {}
        self._enum("summary.verdict", s.get("verdict"), V.VERDICTS, required=True)
        if not s.get("headline"):
            self.errors.append("summary.headline is required")
        if not s.get("conclusion"):
            self.warnings.append("summary.conclusion is empty: it is the paragraph QA pastes on the ticket")
        reqs = self._ids("requirements", qa.get("requirements"), "R")
        for r in qa.get("requirements") or []:
            self._enum("requirement %s source" % r.get("id"), r.get("source"), V.REQ_SOURCES)
            self._enum("requirement %s status" % r.get("id"), r.get("status"), V.REQ_STATUS)
        areas = self._ids("areas", qa.get("areas"), "A")
        for a in qa.get("areas") or []:
            self._enum("area %s test_level" % a.get("id"), a.get("test_level"), V.LEVELS)
            for f in a.get("files") or []:
                self._file("area %s" % a.get("id"), f, None)
            if a.get("entry"):
                self._anchor("area %s entry" % a.get("id"), a["entry"])
        findings = self._ids("findings", qa.get("findings"), "F")
        scenarios = qa.get("scenarios") or []
        if not scenarios:
            self.errors.append("scenarios is empty")
        self._ids("scenarios", scenarios, "T")
        for sc in scenarios:
            self._scenario(sc, reqs, areas, findings)
        for f in qa.get("findings") or []:
            self._enum("finding %s severity" % f.get("id"), f.get("severity"), V.SEVERITIES, required=True)
            self._anchor("finding %s" % f.get("id"), f)
            if not f.get("recommendation"):
                self.warnings.append("finding %s has no recommendation" % f.get("id"))
        self._coverage(scenarios, reqs, areas)
        self._verdict(s.get("verdict"), scenarios)
        return self.errors, self.warnings

    # ---- pieces -------------------------------------------------------------------------
    def _scenario(self, sc, reqs, areas, findings):
        sid = sc.get("id") or "?"
        if not sc.get("title"):
            self.errors.append("scenario %s: title is required" % sid)
        self._enum("scenario %s type" % sid, sc.get("type"), V.TYPES, required=True)
        self._enum("scenario %s level" % sid, sc.get("level"), V.LEVELS)
        self._enum("scenario %s result" % sid, sc.get("result"), V.RESULTS, required=True)
        self._enum("scenario %s as_expected" % sid, sc.get("as_expected"), V.AS_EXPECTED)
        self._enum("scenario %s evidence" % sid, sc.get("evidence"), V.EVIDENCE)
        self._enum("scenario %s environment" % sid, sc.get("environment"), V.ENVIRONMENTS)
        for r in sc.get("requirements") or []:
            if r not in reqs:
                self.errors.append("scenario %s: unknown requirement %s" % (sid, r))
        for a in sc.get("areas") or []:
            if a not in areas:
                self.errors.append("scenario %s: unknown area %s" % (sid, a))
        for f in sc.get("findings") or []:
            if f not in findings:
                self.errors.append("scenario %s: unknown finding %s" % (sid, f))
        for i, st in enumerate(sc.get("steps") or [], 1):
            if not st.get("action"):
                self.errors.append("scenario %s step %d: action is required" % (sid, i))
            self._enum("scenario %s step %d result" % (sid, i), st.get("result"), V.STEP_RESULTS)
            self._anchor("scenario %s step %d" % (sid, i), st)
        for i, c in enumerate(sc.get("code_path") or [], 1):
            self._enum("scenario %s code_path %d role" % (sid, i), c.get("role"), V.ROLES)
            self._anchor("scenario %s code_path %d" % (sid, i), c)
        for k in ("failure", "fix"):
            if sc.get(k):
                self._anchor("scenario %s %s" % (sid, k), sc[k])
        for k in ("run", "log", "trace", "test_file"):
            if sc.get(k):
                self._artifact(sid, k, sc[k])
        for shot in sc.get("screenshots") or []:
            self._artifact(sid, "screenshot", shot)
        if sc.get("evidence") == "executed" and not any(sc.get(k) for k in ("run", "log", "trace", "command", "http", "ui")):
            self.errors.append("scenario %s: evidence=executed needs run / log / trace / command / http / ui" % sid)
        if not sc.get("expected"):
            self.warnings.append("scenario %s: expected outcome is missing" % sid)
        if sc.get("result") in ("passed", "failed") and not sc.get("actual"):
            self.warnings.append("scenario %s: actual outcome is missing" % sid)
        if not sc.get("remarks"):
            self.warnings.append("scenario %s: remarks are empty (the table's last column)" % sid)
        if sc.get("result") == "failed":
            if not (sc.get("failure") or {}).get("reason"):
                self.warnings.append("scenario %s failed: add failure.reason (what went wrong, file:line)" % sid)
            if not (sc.get("fix") or {}).get("description"):
                self.warnings.append("scenario %s failed: add fix.description (how to resolve it)" % sid)
        if sc.get("result") == "blocked" and not sc.get("remarks"):
            self.warnings.append("scenario %s is blocked: say why in remarks" % sid)
        if sc.get("result") in ("passed", "failed") and sc.get("level") != "manual" and not sc.get("code_path"):
            self.warnings.append("scenario %s: code_path is empty: name the classes/methods that ran" % sid)
        if sc.get("evidence") == "static" and sc.get("result") == "passed":
            self.warnings.append("scenario %s passed on static evidence only: say so in remarks/caveats" % sid)
        if sc.get("result") == "passed" and sc.get("as_expected") == "no":
            self.warnings.append("scenario %s: result passed but as_expected is no" % sid)

    def _coverage(self, scenarios, reqs, areas):
        if not reqs:
            self.warnings.append("no requirements: if there was no ticket, list what the code implies (source: code) "
                                 "and add a caveat that the expected behaviour was inferred")
        for r in reqs:
            if not any(r in (s.get("requirements") or []) for s in scenarios):
                self.warnings.append("requirement %s is not covered by any scenario" % r)
        for a in areas:
            if not any(a in (s.get("areas") or []) for s in scenarios):
                self.warnings.append("area %s has no scenario (test it, or explain in not_covered)" % a)
        types = {s.get("type") for s in scenarios}
        if scenarios and not types & set(V.NEGATIVE_TYPES):
            self.warnings.append("only positive scenarios: add invalid / validation / failure / edge-case ones")
        if scenarios and not types & {"success", "valid"}:
            self.warnings.append("no success / valid scenario")

    def _verdict(self, verdict, scenarios):
        results = [s.get("result") for s in scenarios]
        if verdict in ("passed", "passed_with_caveats") and "failed" in results:
            self.warnings.append("verdict is %s but %d scenario(s) failed" % (verdict, results.count("failed")))
        if verdict == "passed" and ("blocked" in results or "not_run" in results or not self.qa.get("requirements")):
            self.warnings.append("verdict is passed but some scenarios did not run or there were no requirements: "
                                 "use passed_with_caveats and list the caveats")
        if verdict == "failed" and "failed" not in results:
            self.warnings.append("verdict is failed but no scenario failed")
        if verdict == "passed_with_caveats" and not self.qa.get("caveats"):
            self.warnings.append("verdict is passed_with_caveats but caveats is empty")

    # ---- helpers ------------------------------------------------------------------------
    def _ids(self, what, items, prefix):
        ids = []
        for i, it in enumerate(items or [], 1):
            if not isinstance(it, dict):
                self.errors.append("%s[%d] must be an object" % (what, i))
                continue
            if not it.get("id"):
                self.errors.append("%s[%d]: id is required (e.g. %s%d)" % (what, i, prefix, i))
            elif it["id"] in ids:
                self.errors.append("%s: duplicate id %s" % (what, it["id"]))
            ids.append(it.get("id"))
        return [x for x in ids if x]

    def _enum(self, where, value, allowed, required=False):
        if value is None:
            if required:
                self.errors.append("%s is required (one of %s)" % (where, ", ".join(allowed)))
            return
        if value not in allowed:
            self.errors.append("%s: %r is not one of %s" % (where, value, ", ".join(allowed)))

    def _anchor(self, where, obj):
        if obj.get("file"):
            self._file(where, obj["file"], obj.get("line"), obj.get("end_line"))

    def _file(self, where, rel, line, end=None):
        if os.path.isabs(rel):
            self.errors.append("%s: file must be repo-relative, got %s" % (where, rel))
            return
        src = self.sources.get(rel)
        if not src.exists:
            self.errors.append("%s: %s does not exist in the working tree" % (where, rel))
            return
        for n in (line, end):
            if n is not None and (not isinstance(n, int) or n < 1 or n > len(src)):
                self.errors.append("%s: %s has %d lines, line %r is out of range" % (where, rel, len(src), n))

    def _artifact(self, sid, kind, rel):
        rel = rel.split("#", 1)[0]
        base = self.repo if rel.startswith(".branch-qa/") else self.out_dir
        if not os.path.exists(os.path.join(base, rel)):
            self.warnings.append("scenario %s: %s %s not found (paths are relative to OUT_DIR)" % (sid, kind, rel))
