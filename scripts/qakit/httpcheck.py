"""HTTP scenarios against a LOCAL server (the app on localhost), with assertions.

A spec is JSON:
  {"base_url": "http://localhost:3000", "headers": {"Accept": "application/json"},
   "requests": [
     {"id": "T1", "name": "Sign in with valid credentials", "method": "POST", "path": "/api/session",
      "json": {"email": "qa@example.com", "password": "{{password}}"},          # or "form": {...} / "body": "raw"
      "expect": {"status": 200, "json": {"user.email": "qa@example.com", "token": {"$exists": true}},
                 "contains": "Welcome", "not_contains": "error", "headers": {"content-type": {"$contains": "json"}},
                 "max_ms": 2000},
      "save": {"token": "json:token", "csrf": "header:x-csrf-token", "next": "cookie:session"}},
     {"id": "T2", "method": "GET", "path": "/api/me", "headers": {"Authorization": "Bearer {{token}}"}, "expect": {"status": 200}}]}

Cookies persist across the requests of one spec (a browser-like session), values saved with
`save` can be used later as {{name}}, and `vars` at the top level seeds them. Only loopback hosts
are allowed unless --allow-host is given: this never talks to staging or production.
Matchers are documented in assertions.py.

  SpecVariables      {{name}} values: seeded by `vars`, filled by `save`, substituted into requests
  HttpRequestBuilder one spec entry -> method, url, headers, body (+ the redacted copy for the report)
  LocalHttpClient    sends it (loopback only, cookies kept, redirects reported, not followed)
  ResponseChecker    the `expect` block -> assertion rows
  HttpCheckRunner    runs a spec, request by request
  HttpCheckDigest    the CLI's one-line-per-request summary
"""
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .assertions import JsonPath, Matcher
from .errors import QAError
from .safety import LocalHosts, Redactor
from .text import Text

BODY_LIMIT = 6000
KEPT_HEADERS = ("content-type", "location", "set-cookie", "x-request-id")


class SpecVariables(object):
    VAR = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")

    def __init__(self, seed=None):
        self.values = dict(seed or {})

    def interpolate(self, value):
        if isinstance(value, str):
            return self.VAR.sub(self._lookup, value)
        if isinstance(value, dict):
            return {k: self.interpolate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.interpolate(v) for v in value]
        return value

    def _lookup(self, m):
        if m.group(1) not in self.values:
            raise QAError("{{%s}} is used before it is saved" % m.group(1))
        return str(self.values[m.group(1)])

    def save(self, rules, headers, data, client):
        """`save` rules: json:<path> | header:<name> | cookie:<name>."""
        for name, src in rules.items():
            kind, _, key = src.partition(":")
            if kind == "json":
                found, v = JsonPath.get(data, key)
                if found:
                    self.values[name] = v
            elif kind == "header" and headers.get(key.lower()) is not None:
                self.values[name] = headers[key.lower()]
            elif kind == "cookie" and client.cookie(key) is not None:
                self.values[name] = client.cookie(key)


class HttpRequestBuilder(object):
    def __init__(self, spec, variables):
        self.spec, self.vars = spec, variables

    def build(self, r):
        """-> (method, url, headers, body bytes or None, redacted description)"""
        v = self.vars
        method = (r.get("method") or "GET").upper()
        url = v.interpolate(r.get("url") or urllib.parse.urljoin(self.spec.get("base_url") or "", r.get("path") or "/"))
        if r.get("query"):
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(v.interpolate(r["query"]), doseq=True)
        headers = v.interpolate(dict(self.spec.get("headers") or {}, **(r.get("headers") or {})))
        body = None
        if "json" in r:
            body = json.dumps(v.interpolate(r["json"])).encode()
            headers.setdefault("Content-Type", "application/json")
        elif "form" in r:
            body = urllib.parse.urlencode(v.interpolate(r["form"]), doseq=True).encode()
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif "body" in r:
            body = v.interpolate(r["body"]).encode()
        shown = {"method": method, "url": url, "headers": Redactor.data(headers),
                 "body": Redactor.data(v.interpolate(r.get("json") or r.get("form"))) if ("json" in r or "form" in r) else r.get("body")}
        return method, url, headers, body, shown


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):      # report 3xx as they are; a scenario asserts on Location
        return None


class LocalHttpClient(object):
    def __init__(self, allow_hosts=(), timeout=30):
        self.hosts, self.timeout = LocalHosts(allow_hosts), timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())

    def send(self, method, url, headers, body):
        """-> (status, lower-cased headers, raw body, milliseconds)"""
        host = urllib.parse.urlsplit(url).hostname
        if not self.hosts.allows(host):
            raise QAError("refusing %s: only local servers (localhost / 127.0.0.1 / *.localhost / *.test) are allowed "
                          "(--allow-host %s to permit it, if it is a local or disposable environment)" % (url, host))
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        t0 = time.time()
        try:
            resp = self.opener.open(req, timeout=self.timeout)
            status, rh, raw = resp.status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as e:
            status, rh, raw = e.code, dict(e.headers.items()), e.read()
        return status, {k.lower(): v for k, v in rh.items()}, raw, int((time.time() - t0) * 1000)

    def cookie(self, name):
        return next((c.value for c in self.jar if c.name == name), None)


class HttpResponse(object):
    """A response as the checks and the report see it."""

    def __init__(self, status, headers, raw, ms):
        self.status, self.headers, self.ms = status, headers, ms
        self.text = raw.decode("utf-8", errors="replace")
        self.data, self.is_json = None, False
        try:
            self.data, self.is_json = json.loads(self.text), True
        except ValueError:
            pass

    def describe(self):
        kept = {k: v for k, v in self.headers.items() if k in KEPT_HEADERS}
        if "set-cookie" in kept:
            kept["set-cookie"] = Redactor.MASK
        return {"status": self.status, "ms": self.ms, "headers": kept,
                "json": Redactor.data(self.data) if self.is_json else None,
                "body": None if self.is_json else self.text[:BODY_LIMIT],
                "truncated": len(self.text) > BODY_LIMIT and not self.is_json}


class ResponseChecker(object):
    """The `expect` block of one request -> [{check, expected, actual, ok}]."""

    @staticmethod
    def check(exp, resp):
        A = []
        if "status" in exp:
            want = exp["status"]
            ok = resp.status in want if isinstance(want, list) else resp.status == want
            A.append({"check": "status", "expected": want, "actual": resp.status, "ok": ok})
        for path, want in (exp.get("json") or {}).items():
            found, actual = JsonPath.get(resp.data, path) if resp.is_json else (False, None)
            ok, desc = Matcher.check(want, found, actual)
            A.append({"check": "json " + path, "expected": desc, "actual": Redactor.data(actual) if found else "(missing)", "ok": ok})
        for s in Text.as_list(exp.get("contains")):
            A.append({"check": "body contains", "expected": s, "actual": "found" if s in resp.text else "not found", "ok": s in resp.text})
        for s in Text.as_list(exp.get("not_contains")):
            A.append({"check": "body excludes", "expected": s, "actual": "found" if s in resp.text else "not found", "ok": s not in resp.text})
        for h, want in (exp.get("headers") or {}).items():
            actual = resp.headers.get(h.lower())
            ok, desc = Matcher.check(want, actual is not None, actual)
            A.append({"check": "header " + h, "expected": desc, "actual": actual, "ok": ok})
        if "max_ms" in exp:
            A.append({"check": "time", "expected": "<= %s ms" % exp["max_ms"], "actual": "%d ms" % resp.ms, "ok": resp.ms <= exp["max_ms"]})
        if not A:
            A.append({"check": "status", "expected": "< 500", "actual": resp.status, "ok": resp.status < 500})
        return A


class HttpCheckRunner(object):
    def __init__(self, spec, allow_hosts=(), only=None):
        self.spec, self.only = spec, set(only or [])
        base = spec.get("base_url")
        if base and not LocalHosts(allow_hosts).allows(urllib.parse.urlsplit(base).hostname):
            raise QAError("base_url %s is not a local server: /branch-qa only sends requests to localhost "
                          "(--allow-host <host> for a local or disposable environment)" % base)
        self.client = LocalHttpClient(allow_hosts, spec.get("timeout", 30))
        self.vars = SpecVariables(spec.get("vars"))
        self.builder = HttpRequestBuilder(spec, self.vars)

    def run(self):
        results = []
        for i, r in enumerate(self.spec.get("requests") or [], 1):
            rid = r.get("id") or "R%d" % i
            if self.only and rid not in self.only:
                continue
            results.append(self.run_one(rid, r))
        return {"base_url": self.spec.get("base_url"), "results": results,
                "passed": sum(1 for x in results if x["result"] == "passed"),
                "failed": sum(1 for x in results if x["result"] != "passed")}

    def run_one(self, rid, r):
        out = {"id": rid, "name": r.get("name") or "", "result": "error", "assertions": []}
        try:
            method, url, headers, body, out["request"] = self.builder.build(r)
            resp = HttpResponse(*self.client.send(method, url, headers, body))
            out["response"] = resp.describe()
            out["assertions"] = ResponseChecker.check(r.get("expect") or {}, resp)
            self.vars.save(r.get("save") or {}, resp.headers, resp.data, self.client)
            out["result"] = "passed" if all(a["ok"] for a in out["assertions"]) else "failed"
        except QAError as e:
            out["error"] = str(e)
        except (urllib.error.URLError, OSError) as e:
            out["error"] = "request failed: %s (is the local server running?)" % getattr(e, "reason", e)
        return out


class HttpCheckDigest(object):
    def __init__(self, result, name):
        self.result, self.name = result, name

    def format(self):
        L = []
        for r in self.result["results"]:
            resp, req = r.get("response") or {}, r.get("request") or {}
            L.append("%-4s %-7s %s %s → %s (%s ms)  %s" % (r["id"], r["result"].upper(), req.get("method", ""), req.get("url", ""),
                                                        resp.get("status", "-"), resp.get("ms", "-"), r.get("name", "")))
            if r.get("error"):
                L.append("       error: " + r["error"])
            L.extend("       ✗ %s: expected %s, got %s" % (x["check"], x["expected"], str(x["actual"])[:200])
                     for x in r["assertions"] if not x["ok"])
        L.append("%d passed, %d failed  RESULT_JSON=runs/%s.json" % (self.result["passed"], self.result["failed"], self.name))
        return "\n".join(L)
