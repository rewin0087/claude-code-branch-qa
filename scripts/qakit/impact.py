"""ImpactAnalyzer: what the branch changed, what reaches it, and how each change should be tested.

LayerClassifier   a changed file -> layer (endpoint, ui, model, service, job, external, ...)
SignalScanner     what the added lines do: HTTP calls, enqueued jobs, callbacks, validation, forms, API calls
EndpointFinder    routes added in the diff, and routes that point at changed controllers / views
CallerFinder      who calls the changed symbols (app code and existing tests), walking up to entry points
TestLevelPlanner  per area: e2e_ui | e2e_api | functional | unit | data | manual, with the reason
"""
import os
import re

from .diffparse import symbol_name
from .sourcefile import SourceCache

# (layer, regex on the repo-relative path); first match wins
LAYERS = [
    ("test", r"(^|/)(spec|tests?|__tests__|e2e|cypress|playwright)/|(_spec\.rb|_test\.(rb|py|go)|\.(test|spec)\.[cm]?[jt]sx?|Test\.(java|kt|php|cs))$|(^|/)test_[^/]+\.py$"),
    ("migration", r"(^|/)(db/migrate|migrations|alembic/versions|prisma/migrations|db/migration|database/migrations)/"),
    ("schema", r"(^|/)(db/schema\.rb|db/structure\.sql|schema\.prisma|schema\.sql)$"),
    ("route", r"(^|/)(config/routes\.rb|config/routes/.+\.rb|urls\.py|routes\.(php|[jt]s|py|go)|routes/.+\.(php|[jt]s|py|rb)|router\.[jt]s)$"),
    ("endpoint", r"(^|/)(app/controllers/|app/api/.+/route\.[jt]s$|pages/api/|app/graphql/|resolvers?/|handlers?/)|"
                 r"([Cc]ontroller\.(java|kt|cs|php|[jt]s)|\.controller\.ts|_controller\.rb|views\.py|viewsets?\.py|api\.py|_handler\.go|endpoints?\.py)$"),
    ("ui", r"\.(tsx|jsx|vue|svelte|erb|haml|slim|html|hbs|ejs|twig|blade\.php|css|scss)$|(^|/)(app/views|app/javascript|app/frontend|components|pages|templates|frontend|client|web/src)/"),
    ("validation", r"(^|/)(validators?|serializers?|forms?|contracts|dto|schemas?|inputs|params|requests)/|"
                   r"(serializers?\.py|forms\.py|schemas?\.py|\.dto\.ts|\.(zod|schema)\.[jt]s|(Request|Dto|Form)\.(java|kt|cs|php))$"),
    ("policy", r"(^|/)(policies|permissions?|abilities|guards|middlewares?|authorization)/|(_policy\.rb|permissions\.py|\.guard\.ts|middleware\.[jt]s)$"),
    ("job", r"(^|/)(app/jobs|app/workers|workers?|jobs|queues?|consumers?|sidekiq|celery)/|(tasks\.py|_job\.rb|_worker\.rb|\.job\.ts|\.worker\.ts|\.processor\.ts)$"),
    ("mailer", r"(^|/)(app/mailers|mailers?|notifications?|notifiers?|emails?)/|(_mailer\.rb|mail\.py|notifications?\.py)$"),
    ("external", r"(^|/)(clients?|integrations?|adapters?|gateways?|connectors?|providers?|webhooks?|api_clients?)/|(_client\.(rb|py|go)|Client\.(java|kt|cs|ts)|\.client\.ts|webhooks?\.py)$"),
    ("callback", r"(^|/)(observers?|listeners?|subscribers?|events?|hooks|signals)/|(signals\.py|_observer\.rb|_listener\.rb|\.subscriber\.ts|\.listener\.ts)$"),
    ("model", r"(^|/)(app/models|models?|entities|entity|domain/models?)/|(models\.py|\.model\.[jt]s|\.entity\.ts|Entity\.(java|kt))$"),
    ("service", r"(^|/)(app/services|services?|interactors?|use_?cases?|operations|commands|domain|lib|app/lib|core|business)/"),
    ("config", r"(^|/)(config|settings|initializers)/|(\.env(\.[\w.-]+)?|settings\.py|\.ya?ml|\.toml|\.ini|Dockerfile|Gemfile(\.lock)?|package(-lock)?\.json|yarn\.lock|requirements[\w.-]*\.txt|pyproject\.toml)$"),
    ("docs", r"\.(md|rst|txt|adoc)$|(^|/)docs?/"),
]
LAYER_RX = [(k, re.compile(r)) for k, r in LAYERS]
CODE_EXT = re.compile(r"\.(rb|py|[cm]?[jt]sx?|go|java|kt|cs|php|ex|exs|rs|scala|vue|svelte)$")
IMPORT_LINE = re.compile(r"^\s*(import|from\s+\S+\s+import|require(_relative)?\b|using\s|include\s)")
ENTRY_LAYERS = ("route", "endpoint", "ui", "job", "callback")

SIGNALS = [
    ("external_http", r"\b(requests\.(get|post|put|patch|delete)|httpx\.|Net::HTTP|Faraday|HTTParty|RestClient|axios\.|got\(|"
                      r"node-fetch|urllib\.request|http\.Client|WebClient|RestTemplate|HttpClient|Http::|Excon|Typhoeus|stripe|Stripe::|twilio|sendgrid|boto3|aws-sdk)\b"),
    ("frontend_api_call", r"\b(fetch\(\s*[`'\"]/|axios\.(get|post|put|patch|delete)\(\s*[`'\"]/|useMutation|useQuery|\$\.ajax|router\.(post|put)|\binertia\.(post|put)|form_with|form_for|simple_form_for|\baction=[\"']/)"),
    ("form", r"(<form\b|onSubmit|handleSubmit|useForm\(|form_with|form_for|simple_form_for|\{% csrf_token %\}|<input\b|<select\b|<textarea\b|v-model|formik|react-hook-form)"),
    ("async_job", r"\b(perform_later|perform_async|perform_in|deliver_later|\.delay\(|apply_async|send_task|enqueue|queue\.add|\.add_job|"
                  r"BackgroundTasks|Thread\.new|Promise\.all|asyncio\.gather|ExecutorService|@Async|run_later|after_commit)\b"),
    ("callback", r"\b(before_|after_|around_)(save|create|update|destroy|commit|validation|action)\b|@receiver\(|post_save|pre_save|"
                 r"@(Pre|Post)(Persist|Update)|@EventListener|\.on\(\s*['\"]|emit\(|publish\(|ActiveSupport::Notifications|dispatch\("),
    ("validation", r"\b(validates?_?\w*|ValidationError|validator|validate|errors\.add|raise .*Invalid|z\.object|Joi\.|yup\.|"
                   r"@Valid|@NotNull|@Size|clean_\w+|serializers\.ValidationError|rules\(|required:\s*true|pattern=)\b"),
    ("db_write", r"\b(save!?|create!?|update!?|update_columns?|destroy!?|delete|insert|upsert|bulk_create|increment!|decrement!|"
                 r"\.objects\.(create|update|filter\(.*\)\.update)|session\.(add|commit|merge)|prisma\.\w+\.(create|update|upsert|delete)|INSERT|UPDATE|DELETE)\b"),
    ("transaction", r"\b(transaction|atomic|with_lock|lock!|select_for_update|FOR UPDATE|\$transaction|BEGIN)\b"),
    ("auth", r"\b(authenticate|authorize|current_user|login_required|permission_classes|before_action :authenticate|"
             r"policy_scope|can\?|cannot\?|has_perm|@PreAuthorize|guard|jwt|session\[)\b"),
    ("mail", r"\b(deliver_now|deliver_later|send_mail|mail\(|EmailMessage|sendgrid|mailer|notify)\b"),
    ("feature_flag", r"\b(Flipper|feature_enabled|flag_enabled|LaunchDarkly|unleash|waffle|feature_flag|FeatureFlag)\b"),
]
SIGNAL_RX = [(k, re.compile(r, re.I if k in ("form",) else 0)) for k, r in SIGNALS]

ROUTE_LINE = [
    re.compile(r"""^\s*(get|post|put|patch|delete|match)\s+['"]([^'"]+)['"](?:.*?(?:to:|=>)\s*['"]([\w/#]+)['"])?"""),        # Rails
    re.compile(r"""^\s*resources?\s+:(\w+)"""),                                                                            # Rails
    re.compile(r"""(?:re_)?path\(\s*r?['"]([^'"]*)['"]\s*,\s*([\w.]+)"""),                                                   # Django
    re.compile(r"""@(?:\w+\.)?(get|post|put|patch|delete|route|api_route)\(\s*['"]([^'"]+)['"]"""),                         # Flask/FastAPI
    re.compile(r"""\b(?:router|app|server|route)\.(get|post|put|patch|delete|all)\(\s*['"`]([^'"`]+)['"`]"""),              # Express
    re.compile(r"""@(Get|Post|Put|Patch|Delete|Request)Mapping\(\s*(?:value\s*=\s*)?["']([^"']*)["']"""),                   # Spring
    re.compile(r"""@(Get|Post|Put|Patch|Delete)\(\s*['"]([^'"]*)['"]"""),                                                    # NestJS
    re.compile(r"""Route::(get|post|put|patch|delete)\(\s*['"]([^'"]+)['"]"""),                                              # Laravel
    re.compile(r"""\.(GET|POST|PUT|PATCH|DELETE|HandleFunc)\(\s*["']([^"']+)["']"""),                                       # Go
]
API_CALL = re.compile(r"""(?:fetch|axios\.(get|post|put|patch|delete)|\$\.ajax|post|put)\(\s*[`'"]([^`'"]*?/[^`'"]*)[`'"]""")
ACTION_ATTR = re.compile(r"""\baction=["']([^"'{}]+)["']|url:\s*['"]([^'"]+)['"]""")


ROUTING_CODE = re.compile(r"@\w+\.(get|post|put|patch|delete|route|api_route)\(|\b(router|app|server)\.(get|post|put|patch|delete|all|use)\(|"
                          r"\bdo_(GET|POST|PUT|PATCH|DELETE)\b|HandleFunc\(|@(Get|Post|Put|Patch|Delete|Request)Mapping|Route::|"
                          r"\burlpatterns\b|\bBaseHTTPRequestHandler\b|\bAPIRouter\(|\bBlueprint\(")


class LayerClassifier(object):
    @staticmethod
    def refine(path, layer, lines):
        """A 'service' / 'other' file that defines HTTP handlers or routes is an endpoint."""
        if layer in ("service", "other", "config") and CODE_EXT.search(path) and lines and \
                any(ROUTING_CODE.search(l) for l in lines[:3000]):
            return "endpoint"
        return layer

    @staticmethod
    def layer(path):
        for key, rx in LAYER_RX:
            if rx.search(path):
                if key == "ui" and re.search(r"\.(css|scss)$", path):
                    return "style"
                return key
        return "service" if CODE_EXT.search(path) else "other"


class SignalScanner(object):
    @staticmethod
    def scan(lines):
        found = {}
        for text in lines:
            for key, rx in SIGNAL_RX:
                if rx.search(text) and len(found.setdefault(key, [])) < 4:
                    found[key].append(text.strip()[:160])
        return found

    @staticmethod
    def api_calls(lines):
        out = []
        for text in lines:
            for m in API_CALL.finditer(text):
                out.append({"method": (m.group(1) or "").upper() or None, "path": m.group(2)})
            for m in ACTION_ATTR.finditer(text):
                out.append({"method": None, "path": m.group(1) or m.group(2)})
        return out[:10]


class EndpointFinder(object):
    def __init__(self, repo, files, sources):
        self.repo, self.files, self.sources = repo, files, sources
        self.route_files = [f for f in files if LayerClassifier.layer(f) == "route"]

    @staticmethod
    def parse_line(text):
        for rx in ROUTE_LINE:
            m = rx.search(text)
            if not m:
                continue
            g = [x for x in m.groups() if x]
            if rx is ROUTE_LINE[1]:
                return {"method": "*", "path": "/" + g[0], "handler": g[0]}
            if len(g) >= 2 and g[0].upper() in ("GET", "POST", "PUT", "PATCH", "DELETE", "MATCH", "ALL", "ROUTE", "API_ROUTE",
                                                 "REQUEST", "HANDLEFUNC"):
                return {"method": g[0].upper(), "path": g[1], "handler": g[2] if len(g) > 2 else None}
            if len(g) >= 2:
                return {"method": "*", "path": "/" + g[0].lstrip("^/"), "handler": g[1]}
        return None

    def added_routes(self, changed):
        out = []
        for cf in changed:
            if LayerClassifier.layer(cf.path) not in ("route", "endpoint"):
                continue
            for n, text in zip(cf.added, cf.added_text):
                r = self.parse_line(text)
                if r:
                    r.update({"file": cf.path, "line": n, "new": True})
                    out.append(r)
        return out

    def routes_for(self, path):
        """Route lines that mention a changed controller / view / handler by its base name."""
        base = re.sub(r"(_controller|Controller|\.controller|_handler|views?|_view|_api)$", "",
                      os.path.splitext(os.path.basename(path))[0])
        if path.endswith(("route.ts", "route.js")) and "/api/" in path:      # Next.js app router
            return [{"method": "*", "path": "/" + path.split("app/", 1)[-1].rsplit("/route.", 1)[0], "file": path, "line": 1}]
        if "pages/api/" in path:
            return [{"method": "*", "path": "/api/" + os.path.splitext(path.split("pages/api/", 1)[1])[0], "file": path, "line": 1}]
        if len(base) < 3:
            return []
        out = []
        word = re.compile(r"\b%s\b" % re.escape(base), re.I)
        for rf in self.route_files[:30]:
            for i, text in enumerate(self.sources.get(rf).lines or [], 1):
                if word.search(text):
                    r = self.parse_line(text) or {"method": "?", "path": text.strip()[:120]}
                    r.update({"file": rf, "line": i})
                    out.append(r)
                    if len(out) >= 8:
                        return out
        return out


class CallerFinder(object):
    def __init__(self, git, max_hits=40):
        self.git, self.max_hits = git, max_hits
        self._cache = {}

    def callers(self, symbol, defined_in):
        """{"app": [(path, line, text)], "tests": [...]} of lines that mention the symbol elsewhere."""
        if symbol in self._cache:
            return self._cache[symbol]
        out = {"app": [], "tests": []}
        if len(symbol) < 4 or symbol in ("call", "perform", "create", "update", "index", "show", "save", "run", "execute",
                                         "initialize", "__init__", "handle", "process", "render", "destroy", "new", "edit"):
            self._cache[symbol] = out
            return out
        defs = re.compile(r"^\s*(def|class|module|function|func|fn|const|let|var|export\s+(default\s+)?(function|class|const))\s")
        for path, line, text in self.git.grep_word(symbol, limit=600):
            if path == defined_in or re.search(r"(^|/)(\.branch-qa|\.investigate|\.branch-review|vendor|node_modules|dist|build)/", path):
                continue
            if defs.match(text) or IMPORT_LINE.match(text) or LayerClassifier.layer(path) in ("docs", "config"):
                continue
            bucket = "tests" if LayerClassifier.layer(path) == "test" else "app"
            if len(out[bucket]) < self.max_hits:
                out[bucket].append((path, line, text.strip()[:160]))
        call = re.compile(r"[.\s(]%s\s*\(|^%s\s*\(|%s\b" % ((re.escape(symbol),) * 2 + (r"\b(?:except|rescue|catch|raise|throw|new)\b.*\b" + re.escape(symbol),)))
        for k in out:      # real calls / raises first, mentions (strings, comments) last
            out[k].sort(key=lambda h: 0 if call.search(h[2]) else 1)
        self._cache[symbol] = out
        return out

    def entry_points(self, symbols, defined_in, sources, depth=2):
        """Entry files (routes, controllers, UI, jobs, callbacks) that reach the symbols within `depth` hops."""
        found, frontier, seen = [], [(s, defined_in) for s in symbols], set()
        for _ in range(depth):
            nxt = []
            for sym, src in frontier:
                for path, line, text in self.callers(sym, src)["app"]:
                    if (path, sym) in seen:
                        continue
                    seen.add((path, sym))
                    layer = LayerClassifier.refine(path, LayerClassifier.layer(path), sources.get(path).lines)
                    if layer in ENTRY_LAYERS:
                        found.append({"file": path, "line": line, "layer": layer, "via": sym, "text": text})
                    else:
                        enclosing = sources.get(path).enclosing_definition(line)
                        if enclosing:
                            name = symbol_name(enclosing["text"])
                            if name:
                                nxt.append((name, path))
            frontier = nxt[:20]
        by_file = {}
        for e in found:          # one entry per file: its first (best) line, and every symbol that leads there
            cur = by_file.get(e["file"])
            if cur is None:
                by_file[e["file"]] = dict(e, via=[e["via"]])
            elif e["via"] not in cur["via"]:
                cur["via"].append(e["via"])
        return [dict(e, via=", ".join(e["via"])) for e in by_file.values()][:15]


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
