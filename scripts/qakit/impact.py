"""ImpactAnalyzer: what the branch changed, what reaches it, and how each change should be tested.

  layers.py    LayerClassifier, SignalScanner   (what kind of code, what the added lines do)
  routes.py    EndpointFinder                   (routes added, routes reaching changed handlers)
  callers.py   CallerFinder                     (callers, covering tests, entry points)
  here         TestLevelPlanner                 (e2e_ui | e2e_api | functional | unit | data | manual + why)
               ImpactAnalyzer                   (puts it together per changed file)
"""
from .callers import CallerFinder
from .layers import CODE_EXT, ENTRY_LAYERS, LayerClassifier, SignalScanner
from .routes import EndpointFinder
from .sourcefile import SourceCache


class TestLevelPlanner(object):
    """The cheapest test level that still proves the behaviour end to end."""

    @staticmethod
    def plan(area, has_browser_tooling):
        layer, sig = area["layer"], area["signals"]
        reaches = {e["layer"] for e in area.get("entry_points", [])}
        if layer in ("ui", "style") and (sig.get("form") or sig.get("frontend_api_call") or area.get("api_calls")):
            if has_browser_tooling:
                return "e2e_ui", "UI form/page that submits to the backend: drive it in a headless browser and follow the request into the API"
            return "e2e_api", "UI form/page that submits to the backend; no browser tooling, so test its API request end to end and list the UI steps for manual QA"
        if layer in ("ui", "style"):
            return ("e2e_ui" if has_browser_tooling else "manual",
                    "UI-only change: check it renders and behaves in a browser" + ("" if has_browser_tooling else " (manual steps; no browser tooling)"))
        if layer in ("route", "endpoint") or area.get("routes"):
            return "e2e_api", "Changes an endpoint: send real requests (framework test client or the local server) and follow them to the DB and side effects"
        if layer == "migration" or layer == "schema":
            return "data", "Schema change: apply it on the test DB, check constraints/defaults and the models that use the new columns"
        if reaches & {"route", "endpoint"}:
            return "e2e_api", "Reached from an endpoint (%s): test through the request so validation, auth and serialisation are included"\
                % ", ".join(sorted({e["file"] for e in area["entry_points"] if e["layer"] in ("route", "endpoint")})[:2])
        if layer in ("job", "mailer", "external", "callback") or sig.get("async_job") or sig.get("external_http"):
            return "functional", "Background/side-effect code: run it inline in the test env with external calls stubbed or blocked, and assert what it persisted or sent"
        if layer in ("service", "model", "validation", "policy"):
            return "functional", "Business logic with no endpoint reaching it directly: call it with real records in the test DB"
        if layer == "test":
            return "unit", "Test-only change: run the changed tests"
        if layer == "config":
            return "manual", "Configuration change: smoke-check the app boots and the affected feature still works"
        return "manual", "No executable behaviour detected: review by reading"


class ImpactAnalyzer(object):
    def __init__(self, workspace, changed, has_browser_tooling=False):
        self.ws, self.changed = workspace, changed
        self.sources = SourceCache(workspace.repo)
        self.callers = CallerFinder(workspace.git)
        self.endpoints = EndpointFinder(workspace.repo, workspace.files, self.sources)
        self.has_browser = has_browser_tooling

    def analyze(self):
        areas, tests_changed = [], []
        for cf in self.changed:
            layer = LayerClassifier.layer(cf.path)
            if layer == "test":
                tests_changed.append(cf.path)
            if cf.status == "deleted" or cf.binary:
                continue
            src = self.sources.get(cf.path).lines
            layer = LayerClassifier.refine(cf.path, layer, src)
            d = cf.to_dict(src)
            d["layer"] = layer
            d["signals"] = SignalScanner.scan(cf.added_text)
            d["api_calls"] = SignalScanner.api_calls(cf.added_text) if layer in ("ui", "style") else []
            d["routes"] = self.endpoints.routes_for(cf.path) if layer in ("endpoint", "ui") else []
            if layer in ("docs", "test", "style", "other") or not CODE_EXT.search(cf.path) and layer not in ("ui", "route", "migration", "schema"):
                d["callers"], d["covering_tests"], d["entry_points"] = [], [], []
            else:
                d["callers"], d["covering_tests"] = self._callers(d["symbols"], cf.path)
                d["entry_points"] = self.callers.entry_points(d["symbols"][:6], cf.path, self.sources) \
                    if layer not in ENTRY_LAYERS else []
            d["test_level"], d["reason"] = TestLevelPlanner.plan(d, self.has_browser)
            areas.append(d)
        for i, a in enumerate(areas, 1):
            a["id"] = "A%d" % i
        return {"areas": areas, "new_routes": self.endpoints.added_routes(self.changed), "tests_changed": tests_changed,
                "levels": self._level_counts(areas)}

    def _callers(self, symbols, path):
        app, tests = [], []
        for s in symbols[:8]:
            c = self.callers.callers(s, path)
            app += [{"symbol": s, "file": p, "line": n, "text": t} for p, n, t in c["app"][:6]]
            tests += [{"symbol": s, "file": p, "line": n} for p, n, t in c["tests"][:6]]
        return app[:25], tests[:20]

    @staticmethod
    def _level_counts(areas):
        out = {}
        for a in areas:
            if a["layer"] not in ("docs", "test"):
                out[a["test_level"]] = out.get(a["test_level"], 0) + 1
        return out
