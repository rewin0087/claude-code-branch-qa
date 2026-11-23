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

  PlaywrightLoader  imports Python Playwright, with an actionable error when it's missing
  Locator           spec locator -> Playwright locator
  ScenarioRecorder  requests / console / page errors / blocked external requests of one scenario
  Screenshots       screenshots under OUT_DIR/screens/
  UiSteps           one method per step kind (actions and expectations)
  StepText          how a step and an error are shown (values of secret fields redacted)
  UiCheckRunner     launches the browser and runs each scenario's steps
  UiCheckDigest     the CLI's summary
"""
import os
import re
import sys
import time
import urllib.parse

from .errors import QAError
from .safety import LocalHosts, Redactor

DEFAULT_TIMEOUT = 10000
EXPECT_TIMEOUT_MS = 5000


class PlaywrightLoader(object):
    @staticmethod
    def load():
        try:
            from playwright.sync_api import sync_playwright  # noqa
            return sync_playwright
        except ImportError:
            raise QAError("Python Playwright is not installed for %s. Ask the user before installing it: "
                          "`python3 -m pip install playwright` (it can use the installed Google Chrome; "
                          "otherwise `python3 -m playwright install chromium`)." % sys.executable)

    @staticmethod
    def launch(p, headed=False):
        """Bundled Chromium first, then the installed Google Chrome."""
        errors = []
        for kw in ({}, {"channel": "chrome"}):
            try:
                return p.chromium.launch(headless=not headed, **kw)
            except Exception as e:     # noqa
                errors.append(str(e).split("\n")[0])
        raise QAError("could not start a headless browser: %s" % " | ".join(errors))


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

    def __init__(self, hosts):
        self.hosts = hosts
        self.requests, self.console, self.page_errors, self.blocked = [], [], [], []

    def attach(self, context, page):
        context.route("**/*", self._route)
        page.on("console", lambda m: m.type == "error" and self.console.append(m.text[:500]))
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:500]))
        page.on("requestfinished", self._finished)
        page.on("requestfailed", lambda r: self._finished(r, failed=True))

    def _route(self, route):
        host = urllib.parse.urlsplit(route.request.url).hostname
        if route.request.url.startswith(("data:", "blob:")) or self.hosts.allows(host):
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

    def find_request(self, method=None, url_contains=None):
        for r in reversed(self.requests):
            if method and r["method"] != method.upper():
                continue
            if url_contains and url_contains not in r["url"]:
                continue
            return r
        return None


class Screenshots(object):
    def __init__(self, workspace, scenario_id):
        self.ws, self.sid, self.paths = workspace, scenario_id, []

    def take(self, page, label):
        rel = os.path.join("screens", "%s-%s.png" % (self.sid, re.sub(r"[^\w-]+", "-", label)[:40]))
        try:
            page.screenshot(path=self.ws.path(rel), full_page=True)
            self.paths.append(rel)
            return rel
        except Exception:     # noqa
            return None


class UiSteps(object):
    """Runs one step on the page. Each step kind is a method named after it; actions return a
    detail (or None), expectations raise AssertionError when they fail."""

    def __init__(self, page, base, recorder, shots):
        self.page, self.base, self.rec, self.shots = page, base, recorder, shots

    def run(self, n, step):
        op = StepText.op(step)
        fn = getattr(self, "do_" + (op or ""), None)
        if fn is None:
            raise QAError("unknown step %r" % op)
        return fn(step[op], step, n)

    # ---- actions --------------------------------------------------------------------------
    def do_goto(self, v, step, n):
        resp = self.page.goto(v if v.startswith("http") else self.base + "/" + v.lstrip("/"))
        return "HTTP %s" % (resp.status if resp else "?")

    def do_fill(self, v, step, n):
        Locator.find(self.page, v).fill(str(v["value"]))

    def do_type(self, v, step, n):
        Locator.find(self.page, v).press_sequentially(str(v["value"]))

    def do_press(self, v, step, n):
        if isinstance(v, dict) and ("selector" in v or "label" in v or "role" in v):
            Locator.find(self.page, v).press(v["key"])
        else:
            self.page.keyboard.press(v if isinstance(v, str) else v["key"])

    def do_click(self, v, step, n):
        Locator.find(self.page, v).click()
        if step.get("wait", True):
            self.page.wait_for_load_state("networkidle", timeout=8000)

    def do_check(self, v, step, n):
        Locator.find(self.page, v).check()

    def do_uncheck(self, v, step, n):
        Locator.find(self.page, v).uncheck()

    def do_select(self, v, step, n):
        Locator.find(self.page, v).select_option(v.get("value") if "value" in v else {"label": v["option"]})

    def do_upload(self, v, step, n):
        Locator.find(self.page, v).set_input_files(v["path"])

    def do_wait_for(self, v, step, n):
        if isinstance(v, str) and not v.startswith(("#", ".", "[", "text=", "role=", "//")):
            self.page.get_by_text(v).first.wait_for()
        else:
            Locator.find(self.page, v).wait_for()

    def do_wait_ms(self, v, step, n):
        self.page.wait_for_timeout(int(v))

    def do_screenshot(self, v, step, n):
        return self.shots.take(self.page, "%02d-%s" % (n, v or "step"))

    # ---- expectations ---------------------------------------------------------------------
    def do_expect_text(self, v, step, n, want=True):
        texts = v if isinstance(v, list) else [v]
        deadline = time.time() + (step.get("timeout_ms") or EXPECT_TIMEOUT_MS) / 1000.0
        while True:           # auto-wait: the page may still be rendering a fetch response
            body = self.page.inner_text("body").lower()
            missing = [t for t in texts if (t.lower() in body) != want]
            if not missing:
                return "ok"
            if time.time() > deadline:
                flash = body.strip().split("\n")[-3:]
                raise AssertionError("%r %s on the page (page ends with: %s)" % (
                    missing[0], "not found" if want else "is still shown", " / ".join(x.strip() for x in flash)[:200]))
            self.page.wait_for_timeout(200)

    def do_expect_no_text(self, v, step, n):
        return self.do_expect_text(v, step, n, want=False)

    def do_expect_visible(self, v, step, n):
        Locator.find(self.page, v).wait_for(state="visible", timeout=EXPECT_TIMEOUT_MS)
        return "ok"

    def do_expect_hidden(self, v, step, n):
        Locator.find(self.page, v).wait_for(state="hidden", timeout=EXPECT_TIMEOUT_MS)
        return "ok"

    def do_expect_value(self, v, step, n):
        actual = Locator.find(self.page, v).input_value()
        if actual != str(v["value"]):
            raise AssertionError("value is %r, expected %r" % (actual, v["value"]))
        return "ok"

    def do_expect_url(self, v, step, n):
        want = v if isinstance(v, str) else v.get("contains")
        self.page.wait_for_load_state("load")
        if want not in self.page.url:
            raise AssertionError("URL is %s, expected it to contain %s" % (self.page.url, want))
        return self.page.url

    def do_expect_title(self, v, step, n):
        if v.lower() not in self.page.title().lower():
            raise AssertionError("title is %r" % self.page.title())
        return "ok"

    def do_expect_request(self, v, step, n):
        """The page sent a matching request (the form -> API hop), optionally with this status."""
        deadline = time.time() + (v.get("timeout_ms") or EXPECT_TIMEOUT_MS) / 1000.0
        while True:
            r = self.rec.find_request(v.get("method"), v.get("url_contains"))
            if r is not None:
                if "status" in v and r["status"] != v["status"]:
                    raise AssertionError("%s %s returned %s, expected %s" % (r["method"], r["url"], r["status"], v["status"]))
                return "%s %s → %s" % (r["method"], r["url"], r["status"])
            if time.time() > deadline:
                raise AssertionError("no %s request to *%s* was made" % (v.get("method") or "", v.get("url_contains") or ""))
            self.page.wait_for_timeout(200)

    def do_expect_no_console_errors(self, v, step, n):
        errs = self.rec.console + self.rec.page_errors
        if errs:
            raise AssertionError("console/page errors: %s" % "; ".join(errs[:3]))
        return "ok"


class StepText(object):
    @staticmethod
    def op(step):
        return next((k for k in step if not k.startswith("_")), None)

    @classmethod
    def describe(cls, step):
        op = cls.op(step) or "?"
        v = step.get(op)
        if isinstance(v, dict):
            v = dict(v)
            if "value" in v and Redactor.is_secret_field(v.get("label") or v.get("selector")):
                v["value"] = Redactor.MASK
            v = ", ".join("%s=%s" % kv for kv in v.items())
        return "%s %s" % (op, v if v is not None else "")

    @staticmethod
    def error(msg):
        msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
        return re.sub(r"\n\s*\n+", "\n", msg).strip()[:800]


class UiCheckRunner(object):
    def __init__(self, workspace, spec, allow_hosts=(), only=None, headed=False):
        self.ws, self.spec, self.only, self.headed = workspace, spec, set(only or []), headed
        self.hosts = LocalHosts(allow_hosts)
        base = spec.get("base_url") or ""
        if not base or not self.hosts.allows(urllib.parse.urlsplit(base).hostname):
            raise QAError("base_url must be a local server (http://localhost:<port>), got %r" % base)
        self.base = base.rstrip("/")

    def run(self):
        sync_playwright = PlaywrightLoader.load()
        results = []
        with sync_playwright() as p:
            browser = PlaywrightLoader.launch(p, self.headed)
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

    def run_one(self, browser, sid, sc):
        ctx = browser.new_context(viewport=self.spec.get("viewport") or {"width": 1280, "height": 800},
                                  base_url=self.base, ignore_https_errors=True)
        ctx.set_default_timeout(self.spec.get("timeout_ms") or DEFAULT_TIMEOUT)
        page = ctx.new_page()
        rec, shots = ScenarioRecorder(self.hosts), Screenshots(self.ws, sid)
        rec.attach(ctx, page)
        runner = UiSteps(page, self.base, rec, shots)
        steps, result, error = [], "passed", None
        all_steps = [dict(s, _before=True) for s in (self.spec.get("before_each") or [])] + list(sc.get("steps") or [])
        for n, step in enumerate(all_steps, 1):
            t0 = time.time()
            entry = {"n": n, "step": StepText.describe(step), "before_each": bool(step.get("_before"))}
            try:
                entry.update({"ok": True, "detail": runner.run(n, step)})
            except Exception as e:     # noqa: a failed step fails the scenario, and the rest are skipped
                entry.update({"ok": False, "detail": StepText.error(str(e))})
                result, error = "failed", "step %d (%s): %s" % (n, entry["step"], StepText.error(str(e)))
            entry["ms"] = int((time.time() - t0) * 1000)
            steps.append(entry)
            if not entry["ok"]:
                break
        shots.take(page, "final" if result == "passed" else "failure")
        out = {"id": sid, "name": sc.get("name") or "", "result": result, "error": error, "steps": steps,
               "url": page.url, "title": self._title(page), "requests": [dict(r, t=None) for r in rec.requests][:60],
               "console_errors": rec.console[:20], "page_errors": rec.page_errors[:20],
               "blocked_external": rec.blocked[:20], "screenshots": shots.paths}
        ctx.close()
        return out

    @staticmethod
    def _title(page):
        try:
            return page.title()
        except Exception:     # noqa
            return None


class UiCheckDigest(object):
    def __init__(self, result, name):
        self.result, self.name = result, name

    def format(self):
        L = []
        for r in self.result["results"]:
            L.append("%-4s %-7s %s" % (r["id"], r["result"].upper(), r["name"]))
            for s in r["steps"]:
                L.append("       %s %s%s" % ("✓" if s["ok"] else "✗", s["step"][:100],
                                             ("  → " + str(s["detail"])[:160]) if s.get("detail") else ""))
            L.extend("       ⇄ %s %s → %s" % (q["method"], q["url"], q["status"] or q.get("failed")) for q in r["requests"][:12])
            L.extend("       console: " + e[:200] for e in r["console_errors"] + r["page_errors"])
            if r["blocked_external"]:
                L.append("       blocked %d external request(s), e.g. %s" % (len(r["blocked_external"]), r["blocked_external"][0]))
            L.append("       screenshots: " + ", ".join(r["screenshots"]))
        L.append("%d passed, %d failed  RESULT_JSON=runs/%s.json" % (self.result["passed"], self.result["failed"], self.name))
        return "\n".join(L)
