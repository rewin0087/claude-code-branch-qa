"""Running a test command and turning its output into per-test results.

EnvGuard       refuses commands aimed at production (RAILS_ENV/NODE_ENV/APP_ENV=production, remote DATABASE_URL)
JUnitParser    JUnit XML (pytest --junitxml, rspec_junit_formatter, jest-junit, vitest, playwright, go-junit) -> cases
OutputParser   the runner's own summary line(s): pytest, rspec, minitest, jest/vitest, go, phpunit, playwright, cypress, django
TestRun        runs the command with a timeout, saves the log under logs/, writes runs/<id>.json
"""
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from .errors import QAError
from .jsonio import write_json

PROD = re.compile(r"\b(RAILS_ENV|RACK_ENV|NODE_ENV|APP_ENV|DJANGO_ENV|FLASK_ENV|ENVIRONMENT|ASPNETCORE_ENVIRONMENT|MIX_ENV)\s*=\s*['\"]?prod(uction)?\b", re.I)
DB_URL = re.compile(r"\b(DATABASE_URL|DB_HOST|PGHOST|MYSQL_HOST)\s*=\s*['\"]?([^\s'\"]+)")
LOCAL_HOST = re.compile(r"(localhost|127\.0\.0\.1|::1|0\.0\.0\.0|\.local\b|\.test\b|sqlite|^db$|^postgres$|^mysql$|@db[:/]|@postgres[:/]|@mysql[:/])", re.I)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOG_TAIL = 12000


class EnvGuard(object):
    @staticmethod
    def check(cmd_text, env):
        joined = cmd_text + " " + " ".join("%s=%s" % kv for kv in env.items())
        if PROD.search(joined):
            raise QAError("refusing to run: the command targets a production environment")
        for m in DB_URL.finditer(joined):
            if not LOCAL_HOST.search(m.group(2)):
                raise QAError("refusing to run: %s points at a non-local database (%s)" % (m.group(1), m.group(2).split("@")[-1][:60]))


class JUnitParser(object):
    @staticmethod
    def parse(path):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as e:
            raise QAError("could not read JUnit XML %s: %s" % (path, e))
        cases = []
        for tc in root.iter("testcase"):
            status, message = "passed", None
            for tag, st in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
                el = tc.find(tag)
                if el is not None:
                    status = st
                    message = (el.get("message") or el.text or "").strip()[:1500]
                    break
            cases.append({"name": tc.get("name"), "classname": tc.get("classname"), "file": tc.get("file"),
                          "time": float(tc.get("time") or 0), "status": status, "message": message})
        return cases


class OutputParser(object):
    PATTERNS = [
        # (runner, regex, groups -> counts)
        ("pytest", re.compile(r"=+ (.*?(?:passed|failed|error|skipped|no tests ran).*?) in [\d.]+s"), None),
        ("rspec", re.compile(r"(\d+) examples?, (\d+) failures?(?:, (\d+) pending)?"), ("total", "failed", "skipped")),
        ("minitest", re.compile(r"(\d+) runs, \d+ assertions, (\d+) failures, (\d+) errors(?:, (\d+) skips)?"), ("total", "failed", "errors", "skipped")),
        ("jest", re.compile(r"Tests:\s+(.*?total)"), None),
        ("vitest", re.compile(r"Tests\s+(.*?\(\d+\))"), None),
        ("playwright", re.compile(r"^\s*(\d+) (passed|failed|flaky|skipped)", re.M), None),
        ("cypress", re.compile(r"(All specs passed!|\d+ of \d+ failed)"), None),
        ("unittest", re.compile(r"Ran (\d+) tests? in [\d.]+s\s+(OK|FAILED.*)"), None),
        ("phpunit", re.compile(r"(OK \(\d+ tests?.*?\)|Tests: \d+.*?(Failures|Errors): \d+.*)"), None),
        ("go", re.compile(r"^(ok|FAIL)\s+\S+", re.M), None),
    ]

    @staticmethod
    def summary(text):
        found = []
        for runner, rx, _ in OutputParser.PATTERNS:
            for m in rx.finditer(text):
                found.append({"runner": runner, "line": m.group(0).strip()[:200]})
        return found[-6:]

    @staticmethod
    def failures(text, limit=15):
        """Names of failing tests as the runners print them."""
        out = []
        for rx in (re.compile(r"^FAILED (\S+)(?: - (.*))?$", re.M),                       # pytest -q
                   re.compile(r"^rspec (\./\S+:\d+) # (.*)$", re.M),                       # rspec
                   re.compile(r"^\s*●\s+(.+?)\s*$", re.M),                                 # jest
                   re.compile(r"^\s*(?:FAIL|×|✗)\s+(.+?)\s*$", re.M),                      # vitest / go / playwright
                   re.compile(r"^(?:FAIL|ERROR): (\w+) \(([\w.]+)\)", re.M)):              # django / unittest
            for m in rx.finditer(text):
                name = " ".join(g for g in m.groups() if g)
                if name not in out:
                    out.append(name[:300])
        return out[:limit]


class TestRun(object):
    def __init__(self, workspace, run_id, cmd, env=None, cwd=None, timeout=900, junit=None):
        if not re.match(r"^[\w.-]+$", run_id or ""):
            raise QAError("--id must be letters, digits, dot, dash or underscore")
        self.ws, self.id, self.cmd = workspace, run_id, cmd
        self.env, self.cwd = dict(env or {}), cwd or workspace.repo
        self.timeout, self.junit = timeout, junit

    def run(self):
        cmd_text = " ".join(self.cmd)
        EnvGuard.check(cmd_text, self.env)
        env = dict(os.environ, **self.env)
        t0 = time.time()
        log_rel = os.path.join("logs", "%s.txt" % self.id)
        timed_out = False
        try:
            p = subprocess.run(self.cmd, cwd=self.cwd, env=env, capture_output=True, text=True, errors="replace",
                               timeout=self.timeout)
            code, output = p.returncode, (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
        except subprocess.TimeoutExpired as e:
            timed_out, code = True, None
            output = _text(e.stdout) + "\n" + _text(e.stderr) + "\n[qa] TIMED OUT after %ss" % self.timeout
        except OSError as e:
            raise QAError("could not start %s: %s" % (self.cmd[0], e))
        output = ANSI.sub("", output)
        with open(self.ws.path(log_rel), "w") as fh:
            fh.write("$ %s%s\n(cwd %s)\n\n%s" % (" ".join("%s=%s" % kv for kv in self.env.items()) + " " if self.env else "",
                                                 cmd_text, self.cwd, output))
        cases = JUnitParser.parse(self.junit) if self.junit and os.path.exists(self.junit) else []
        result = {"id": self.id, "cmd": cmd_text, "env": self.env, "cwd": self.cwd, "exit_code": code, "timed_out": timed_out,
                  "duration_ms": int((time.time() - t0) * 1000), "log": log_rel,
                  "status": "passed" if code == 0 else ("blocked" if timed_out else "failed"),
                  "summary": OutputParser.summary(output), "failures": OutputParser.failures(output),
                  "cases": cases, "tail": output[-LOG_TAIL:]}
        write_json(self.ws.path("runs", "%s.json" % self.id), result)
        return result


def _text(b):
    if b is None:
        return ""
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else b
