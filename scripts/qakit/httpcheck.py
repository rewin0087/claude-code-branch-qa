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

Matchers: a plain value (equality), or {"$exists": bool} {"$ne": v} {"$contains": s} {"$regex": r}
{"$gt": n} {"$gte": n} {"$lt": n} {"$lte": n} {"$len": n} {"$type": "string|number|bool|null|list|object"}
{"$in": [..]}.
"""
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import QAError

LOOPBACK = ("localhost", "127.0.0.1", "::1", "0.0.0.0")
SECRET_KEY = re.compile(r"(pass(wd|word)?|secret|token|api_?key|authorization|cookie|otp|cvv|card)", re.I)
VAR = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")
BODY_LIMIT = 6000


def is_local(host, allowed=()):
    host = (host or "").lower().strip("[]")
    return host in LOOPBACK or host.endswith(".localhost") or host.endswith(".test") or host in allowed


class JsonPath(object):
    """`a.b[0].c` / `a.b.0.c` -> (found, value)"""

    @staticmethod
    def get(data, path):
        cur = data
        if path in ("", "$", "."):
            return True, data
        for part in re.findall(r"[^.\[\]]+", path):
            if isinstance(cur, list) and re.match(r"^-?\d+$", part):
                i = int(part)
                if -len(cur) <= i < len(cur):
                    cur = cur[i]
                    continue
                return False, None
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
                continue
            return False, None
        return True, cur


TYPES = {"string": str, "number": (int, float), "bool": bool, "null": type(None), "list": list, "object": dict}


class Matcher(object):
    @staticmethod
    def check(expected, found, actual):
        """-> (ok, description of the expectation)"""
        if isinstance(expected, dict) and expected and all(k.startswith("$") for k in expected):
            for op, v in expected.items():
                ok = Matcher._op(op, v, found, actual)
                if not ok:
                    return False, "%s %s" % (op, json.dumps(v))
            return True, " ".join("%s %s" % (k, json.dumps(v)) for k, v in expected.items())
        return found and actual == expected, "== %s" % json.dumps(expected, default=str)

    @staticmethod
    def _op(op, v, found, actual):
        try:
            if op == "$exists":
                return found == bool(v) and (not v or actual is not None)
            if not found and op != "$ne":
                return False
            if op == "$ne":
                return actual != v
            if op == "$contains":
                return (v in actual) if isinstance(actual, (list, dict)) else str(v).lower() in str(actual).lower()
            if op == "$regex":
                return re.search(v, str(actual)) is not None
            if op == "$gt":
                return actual > v
            if op == "$gte":
                return actual >= v
            if op == "$lt":
                return actual < v
            if op == "$lte":
                return actual <= v
            if op == "$len":
                return len(actual) == v
            if op == "$type":
                return isinstance(actual, TYPES[v]) and not (v == "number" and isinstance(actual, bool))
            if op == "$in":
                return actual in v
        except (TypeError, KeyError):
            return False
        raise QAError("unknown matcher %s" % op)


def redact(obj):
    if isinstance(obj, dict):
        return {k: ("[redacted]" if SECRET_KEY.search(str(k)) and v not in (None, "") else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):      # report 3xx as they are; a scenario asserts on Location
        return None


class LocalHttpClient(object):
    def __init__(self, allow_hosts=(), timeout=30):
        self.allow, self.timeout = tuple(h.lower() for h in allow_hosts), timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())

    def send(self, method, url, headers, body):
        host = urllib.parse.urlsplit(url).hostname
        if not is_local(host, self.allow):
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


class HttpCheckRunner(object):
    def __init__(self, spec, allow_hosts=(), only=None):
        self.spec, self.only = spec, set(only or [])
        self.client = LocalHttpClient(allow_hosts, spec.get("timeout", 30))
        self.vars = dict(spec.get("vars") or {})
        base = spec.get("base_url")
        if base and not is_local(urllib.parse.urlsplit(base).hostname, tuple(h.lower() for h in allow_hosts)):
            raise QAError("base_url %s is not a local server: /qa only sends requests to localhost "
                          "(--allow-host <host> for a local or disposable environment)" % base)

    def interpolate(self, value):
        if isinstance(value, str):
            def rep(m):
                if m.group(1) not in self.vars:
                    raise QAError("{{%s}} is used before it is saved" % m.group(1))
                return str(self.vars[m.group(1)])
            return VAR.sub(rep, value)
        if isinstance(value, dict):
            return {k: self.interpolate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.interpolate(v) for v in value]
        return value

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
            method = (r.get("method") or "GET").upper()
            url = self.interpolate(r.get("url") or urllib.parse.urljoin(self.spec.get("base_url") or "", r.get("path") or "/"))
            if r.get("query"):
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(self.interpolate(r["query"]), doseq=True)
            headers = self.interpolate(dict(self.spec.get("headers") or {}, **(r.get("headers") or {})))
            body = None
            if "json" in r:
                body = json.dumps(self.interpolate(r["json"])).encode()
                headers.setdefault("Content-Type", "application/json")
            elif "form" in r:
                body = urllib.parse.urlencode(self.interpolate(r["form"]), doseq=True).encode()
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif "body" in r:
                body = self.interpolate(r["body"]).encode()
            out["request"] = {"method": method, "url": url, "headers": redact(headers),
                              "body": redact(self.interpolate(r.get("json") or r.get("form"))) if ("json" in r or "form" in r) else r.get("body")}
            status, rh, raw, ms = self.client.send(method, url, headers, body)
            text = raw.decode("utf-8", errors="replace")
            data, is_json = None, False
            try:
                data, is_json = json.loads(text), True
            except ValueError:
                pass
            out["response"] = {"status": status, "ms": ms, "headers": {k: v for k, v in rh.items()
                                                                       if k in ("content-type", "location", "set-cookie", "x-request-id")},
                               "json": redact(data) if is_json else None, "body": None if is_json else text[:BODY_LIMIT],
                               "truncated": len(text) > BODY_LIMIT and not is_json}
            if "set-cookie" in out["response"]["headers"]:
                out["response"]["headers"]["set-cookie"] = "[redacted]"
            out["assertions"] = self.assert_all(r.get("expect") or {}, status, rh, text, data, is_json, ms)
            self.save(r.get("save") or {}, rh, data)
            out["result"] = "passed" if all(a["ok"] for a in out["assertions"]) else "failed"
        except QAError as e:
            out["error"] = str(e)
        except (urllib.error.URLError, OSError) as e:
            out["error"] = "request failed: %s (is the local server running?)" % getattr(e, "reason", e)
        return out

    def assert_all(self, exp, status, rh, text, data, is_json, ms):
        A = []
        if "status" in exp:
            want = exp["status"]
            ok = status in want if isinstance(want, list) else status == want
            A.append({"check": "status", "expected": want, "actual": status, "ok": ok})
        for path, want in (exp.get("json") or {}).items():
            found, actual = JsonPath.get(data, path) if is_json else (False, None)
            ok, desc = Matcher.check(want, found, actual)
            A.append({"check": "json " + path, "expected": desc, "actual": redact(actual) if found else "(missing)", "ok": ok})
        for s in _as_list(exp.get("contains")):
            A.append({"check": "body contains", "expected": s, "actual": "found" if s in text else "not found", "ok": s in text})
        for s in _as_list(exp.get("not_contains")):
            A.append({"check": "body excludes", "expected": s, "actual": "found" if s in text else "not found", "ok": s not in text})
        for h, want in (exp.get("headers") or {}).items():
            actual = rh.get(h.lower())
            ok, desc = Matcher.check(want, actual is not None, actual)
            A.append({"check": "header " + h, "expected": desc, "actual": actual, "ok": ok})
        if "max_ms" in exp:
            A.append({"check": "time", "expected": "<= %s ms" % exp["max_ms"], "actual": "%d ms" % ms, "ok": ms <= exp["max_ms"]})
        if not A:
            A.append({"check": "status", "expected": "< 500", "actual": status, "ok": status < 500})
        return A

    def save(self, rules, rh, data):
        for name, src in rules.items():
            kind, _, key = src.partition(":")
            if kind == "json":
                found, v = JsonPath.get(data, key)
                if found:
                    self.vars[name] = v
            elif kind == "header" and rh.get(key.lower()) is not None:
                self.vars[name] = rh[key.lower()]
            elif kind == "cookie" and self.client.cookie(key) is not None:
                self.vars[name] = self.client.cookie(key)


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])
