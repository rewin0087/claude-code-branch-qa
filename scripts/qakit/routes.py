"""EndpointFinder: routes added on the branch, and routes that point at a changed controller / view."""
import os
import re

from .layers import LayerClassifier

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
