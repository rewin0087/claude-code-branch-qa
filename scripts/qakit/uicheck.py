"""Headless browser scenarios (Python Playwright) against the app running on localhost.

A spec is JSON:
  {"base_url": "http://localhost:3000", "viewport": {"width": 1280, "height": 800},
   "before_each": [{"goto": "/login"}, {"fill": {"label": "Email", "value": "qa@example.com"}}, ...],
   "scenarios": [
     {"id": "T4", "name": "Refund form rejects an amount over the remaining balance",
      "steps": [
        {"goto": "/orders/4512"},
        {"fill": {"selector": "#refund_amount", "value": "600"}},
        {"click": {"role": "button", "name": "Refund"}},
        {"expect_text": "exceeds the remaining amount"},
        {"expect_request": {"method": "POST", "url_contains": "/refunds", "status": 422}},
        {"expect_url": "/orders/4512"},
        {"screenshot": "rejected"}]}]}

Locators: a string is a Playwright selector ("#id", "text=Save", "role=button[name='Save']");
an object picks one of selector | label | role (+ name) | placeholder | text | testid.
Steps: goto, fill, type, press, click, check, uncheck, select, upload, wait_for, wait_ms,
expect_text, expect_no_text, expect_visible, expect_hidden, expect_value, expect_url,
expect_title, expect_request, expect_no_console_errors, screenshot.

Every scenario records the same-origin requests the page made (method, URL, status: the form
-> API hop), console errors, page errors and a screenshot after the last step (and on failure).
Requests to non-local hosts are aborted unless --allow-host is given.
"""
import os
import re
import sys
import time
import urllib.parse

from .errors import QAError
from .httpcheck import is_local

DEFAULT_TIMEOUT = 10000


def load_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa
        return sync_playwright
    except ImportError:
        raise QAError("Python Playwright is not installed for %s. Ask the user before installing it: "
                      "`python3 -m pip install playwright` (it can use the installed Google Chrome; "
                      "otherwise `python3 -m playwright install chromium`)." % sys.executable)


class Locator(object):
    @staticmethod
    def find(page, spec):
        if isinstance(spec, str):
            return page.locator(spec).first
        if "selector" in spec:
            return page.locator(spec["selector"]).first
        if "label" in spec:
            return page.get_by_label(spec["label"], exact=spec.get("exact", False)).first
        if "role" in spec:
            return page.get_by_role(spec["role"], name=spec.get("name"), exact=spec.get("exact", False)).first
        if "placeholder" in spec:
            return page.get_by_placeholder(spec["placeholder"]).first
        if "testid" in spec:
            return page.get_by_test_id(spec["testid"]).first
        if "text" in spec:
            return page.get_by_text(spec["text"], exact=spec.get("exact", False)).first
        raise QAError("can't locate %r: use selector | label | role | placeholder | text | testid" % spec)


class ScenarioRecorder(object):
    """What the page did while a scenario ran."""

    def __init__(self, origin, allow_hosts):
        self.origin, self.allow = origin, allow_hosts
        self.requests, self.console, self.page_errors, self.blocked = [], [], [], []

    def attach(self, context, page):
        context.route("**/*", self._route)
        page.on("console", lambda m: m.type == "error" and self.console.append(m.text[:500]))
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:500]))
        page.on("requestfinished", self._finished)
        page.on("requestfailed", lambda r: self._finished(r, failed=True))

    def _route(self, route):
        host = urllib.parse.urlsplit(route.request.url).hostname
        if route.request.url.startswith(("data:", "blob:")) or is_local(host, self.allow):
            return route.continue_()
        self.blocked.append(route.request.url[:200])
        return route.abort()

    def _finished(self, req, failed=False):
        if req.resource_type not in ("xhr", "fetch", "document", "form") and req.method == "GET":
            return
        status = None
        if not failed:
            try:
                resp = req.response()
                status = resp.status if resp else None
            except Exception:   # noqa
                pass
        self.requests.append({"method": req.method, "url": req.url[:300], "type": req.resource_type, "status": status,
                              "failed": req.failure if failed else None, "t": time.time()})


class UiCheckRunner(object):
    def __init__(self, workspace, spec, allow_hosts=(), only=None, headed=False):
        self.ws, self.spec, self.only, self.headed = workspace, spec, set(only or []), headed
        self.allow = tuple(allow_hosts)
        base = spec.get("base_url") or ""
        host = urllib.parse.urlsplit(base).hostname
        if not base or not is_local(host, self.allow):
            raise QAError("base_url must be a local server (http://localhost:<port>), got %r" % base)
        self.base = base.rstrip("/")

    def run(self):
        sync_playwright = load_playwright()
        results = []
        with sync_playwright() as p:
            browser = self._launch(p)
            try:
                for i, sc in enumerate(self.spec.get("scenarios") or [], 1):
                    sid = sc.get("id") or "U%d" % i
                    if self.only and sid not in self.only:
                        continue
                    results.append(self.run_one(browser, sid, sc))
            finally:
                browser.close()
        return {"base_url": self.base, "results": results,
                "passed": sum(1 for r in results if r["result"] == "passed"),
                "failed": sum(1 for r in results if r["result"] != "passed")}

    def _launch(self, p):
        errors = []
        for kw in ({}, {"channel": "chrome"}):
            try:
                return p.chromium.launch(headless=not self.headed, **kw)
            except Exception as e:     # noqa
                errors.append(str(e).split("\n")[0])
        raise QAError("could not start a headless browser: %s" % " | ".join(errors))

    def run_one(self, browser, sid, sc):
        ctx = browser.new_context(viewport=self.spec.get("viewport") or {"width": 1280, "height": 800},
                                  base_url=self.base, ignore_https_errors=True)
        ctx.set_default_timeout(self.spec.get("timeout_ms") or DEFAULT_TIMEOUT)
        page = ctx.new_page()
        rec = ScenarioRecorder(self.base, self.allow)
        rec.attach(ctx, page)
        steps, shots, result, error = [], [], "passed", None
        all_steps = [dict(s, _before=True) for s in (self.spec.get("before_each") or [])] + list(sc.get("steps") or [])
        for n, step in enumerate(all_steps, 1):
            t0 = time.time()
            entry = {"n": n, "step": _describe(step), "before_each": bool(step.get("_before"))}
            try:
                detail = self.do(page, step, rec, sid, n, shots)
                entry.update({"ok": True, "detail": detail})
            except Exception as e:     # noqa: a failed step fails the scenario, and the rest are skipped
                entry.update({"ok": False, "detail": _clean(str(e))})
                result, error = "failed", "step %d (%s): %s" % (n, entry["step"], _clean(str(e)))
            entry["ms"] = int((time.time() - t0) * 1000)
            steps.append(entry)
            if not entry["ok"]:
                break
        shots.append(self._shot(page, sid, "final" if result == "passed" else "failure"))
        out = {"id": sid, "name": sc.get("name") or "", "result": result, "error": error, "steps": steps,
               "url": page.url, "title": _safe(page.title), "requests": [dict(r, t=None) for r in rec.requests][:60],
               "console_errors": rec.console[:20], "page_errors": rec.page_errors[:20],
               "blocked_external": rec.blocked[:20], "screenshots": [s for s in shots if s]}
        ctx.close()
        return out

    def _shot(self, page, sid, label):
        rel = os.path.join("screens", "%s-%s.png" % (sid, re.sub(r"[^\w-]+", "-", label)[:40]))
        try:
            page.screenshot(path=self.ws.path(rel), full_page=True)
            return rel
        except Exception:     # noqa
            return None

    def do(self, page, step, rec, sid, n, shots):
        op = next((k for k in step if not k.startswith("_")), None)
        v = step[op]
        if op == "goto":
            resp = page.goto(v if v.startswith("http") else self.base + "/" + v.lstrip("/"))
            return "HTTP %s" % (resp.status if resp else "?")
        if op in ("fill", "type"):
            loc = Locator.find(page, v)
            loc.fill(str(v["value"])) if op == "fill" else loc.press_sequentially(str(v["value"]))
            return None
        if op == "press":
            Locator.find(page, v).press(v["key"]) if isinstance(v, dict) and ("selector" in v or "label" in v or "role" in v) \
                else page.keyboard.press(v if isinstance(v, str) else v["key"])
            return None
        if op == "click":
            Locator.find(page, v).click()
            page.wait_for_load_state("networkidle", timeout=8000) if step.get("wait", True) else None
            return None
        if op in ("check", "uncheck"):
            getattr(Locator.find(page, v), op)()
            return None
        if op == "select":
            Locator.find(page, v).select_option(v.get("value") if "value" in v else {"label": v["option"]})
            return None
        if op == "upload":
            Locator.find(page, v).set_input_files(v["path"])
            return None
        if op == "wait_for":
            if isinstance(v, str) and not v.startswith(("#", ".", "[", "text=", "role=", "//")):
                page.get_by_text(v).first.wait_for()
            else:
                Locator.find(page, v).wait_for()
            return None
        if op == "wait_ms":
            page.wait_for_timeout(int(v))
            return None
        if op in ("expect_text", "expect_no_text"):
            texts = v if isinstance(v, list) else [v]
            want = op == "expect_text"
            deadline = time.time() + (step.get("timeout_ms") or 5000) / 1000.0
            while True:           # auto-wait: the page may still be rendering a fetch response
                body = page.inner_text("body").lower()
                missing = [t for t in texts if (t.lower() in body) != want]
                if not missing:
                    return "ok"
                if time.time() > deadline:
                    flash = body.strip().split("\n")[-3:]
                    raise AssertionError("%r %s on the page (page ends with: %s)" % (
                        missing[0], "not found" if want else "is still shown", " / ".join(x.strip() for x in flash)[:200]))
                page.wait_for_timeout(200)
        if op in ("expect_visible", "expect_hidden"):
            loc = Locator.find(page, v)
            loc.wait_for(state="visible" if op == "expect_visible" else "hidden", timeout=5000)
            return "ok"
        if op == "expect_value":
            actual = Locator.find(page, v).input_value()
            if actual != str(v["value"]):
                raise AssertionError("value is %r, expected %r" % (actual, v["value"]))
            return "ok"
        if op == "expect_url":
            want = v if isinstance(v, str) else v.get("contains")
            page.wait_for_load_state("load")
            if want not in page.url:
                raise AssertionError("URL is %s, expected it to contain %s" % (page.url, want))
            return page.url
        if op == "expect_title":
            if v.lower() not in page.title().lower():
                raise AssertionError("title is %r" % page.title())
            return "ok"
        if op == "expect_request":
            return self._expect_request(page, v, rec)
        if op == "expect_no_console_errors":
            errs = rec.console + rec.page_errors
            if errs:
                raise AssertionError("console/page errors: %s" % "; ".join(errs[:3]))
            return "ok"
        if op == "screenshot":
            shots.append(self._shot(page, sid, "%02d-%s" % (n, v or "step")))
            return shots[-1]
        raise QAError("unknown step %r" % op)

    @staticmethod
    def _expect_request(page, v, rec):
        deadline = time.time() + (v.get("timeout_ms") or 5000) / 1000.0
        while True:
            for r in reversed(rec.requests):
                if v.get("method") and r["method"] != v["method"].upper():
                    continue
                if v.get("url_contains") and v["url_contains"] not in r["url"]:
                    continue
                if "status" in v and r["status"] != v["status"]:
                    raise AssertionError("%s %s returned %s, expected %s" % (r["method"], r["url"], r["status"], v["status"]))
                return "%s %s → %s" % (r["method"], r["url"], r["status"])
            if time.time() > deadline:
                raise AssertionError("no %s request to *%s* was made" % (v.get("method") or "", v.get("url_contains") or ""))
            page.wait_for_timeout(200)


def _describe(step):
    op = next((k for k in step if not k.startswith("_")), "?")
    v = step.get(op)
    if isinstance(v, dict):
        v = dict(v)
        if "value" in v and re.search(r"pass|secret|token", str(v.get("label") or v.get("selector") or ""), re.I):
            v["value"] = "[redacted]"
        v = ", ".join("%s=%s" % kv for kv in v.items())
    return "%s %s" % (op, v if v is not None else "")


def _clean(msg):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
    return re.sub(r"\n\s*\n+", "\n", msg).strip()[:800]


def _safe(fn):
    try:
        return fn()
    except Exception:     # noqa
        return None
