"""Running a test command and turning its output into per-test results.

JUnitParser    JUnit XML (pytest --junitxml, rspec_junit_formatter, jest-junit, vitest, playwright, go-junit) -> cases
OutputParser   the runner's own summary line(s): pytest, rspec, minitest, jest/vitest, go, phpunit, playwright, cypress, django
ProcessRunner  runs a command with a timeout and returns its exit code and combined output
TestRun        guards + runs the command, saves the log under logs/, writes runs/<id>.json
TestRunDigest  the CLI's summary of one run
(EnvGuard, which refuses production targets, lives in safety.py.)
"""
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from .errors import QAError
from .jsonio import JsonFile
from .safety import EnvGuard

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOG_TAIL = 12000


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


class ProcessRunner(object):
    def __init__(self, cmd, env, cwd, timeout):
        self.cmd, self.env, self.cwd, self.timeout = cmd, env, cwd, timeout

    def run(self):
        """-> (exit code or None on timeout, output with ANSI colours removed, timed out?)"""
        try:
            p = subprocess.run(self.cmd, cwd=self.cwd, env=dict(os.environ, **self.env), capture_output=True, text=True,
                               errors="replace", timeout=self.timeout)
            code, output, timed_out = p.returncode, (p.stdout or "") + ("\n" + p.stderr if p.stderr else ""), False
        except subprocess.TimeoutExpired as e:
            code, timed_out = None, True
            output = self._decode(e.stdout) + "\n" + self._decode(e.stderr) + "\n[qa] TIMED OUT after %ss" % self.timeout
        except OSError as e:
            raise QAError("could not start %s: %s" % (self.cmd[0], e))
        return code, ANSI.sub("", output), timed_out

    @staticmethod
    def _decode(b):
        if b is None:
            return ""
        return b.decode("utf-8", "replace") if isinstance(b, bytes) else b


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
        t0 = time.time()
        code, output, timed_out = ProcessRunner(self.cmd, self.env, self.cwd, self.timeout).run()
        log_rel = os.path.join("logs", "%s.txt" % self.id)
        self._write_log(log_rel, cmd_text, output)
        cases = JUnitParser.parse(self.junit) if self.junit and os.path.exists(self.junit) else []
        result = {"id": self.id, "cmd": cmd_text, "env": self.env, "cwd": self.cwd, "exit_code": code, "timed_out": timed_out,
                  "duration_ms": int((time.time() - t0) * 1000), "log": log_rel,
                  "status": "passed" if code == 0 else ("blocked" if timed_out else "failed"),
                  "summary": OutputParser.summary(output), "failures": OutputParser.failures(output),
                  "cases": cases, "tail": output[-LOG_TAIL:]}
        JsonFile.write(self.ws.path("runs", "%s.json" % self.id), result)
        return result

    def _write_log(self, rel, cmd_text, output):
        env = " ".join("%s=%s" % kv for kv in self.env.items()) + " " if self.env else ""
        with open(self.ws.path(rel), "w") as fh:
            fh.write("$ %s%s\n(cwd %s)\n\n%s" % (env, cmd_text, self.cwd, output))


class TestRunDigest(object):
    def __init__(self, result):
        self.r = result

    def format(self):
        r = self.r
        L = ["RUN %s: %s (exit %s, %d ms)  log=%s" % (r["id"], r["status"].upper(), r["exit_code"], r["duration_ms"], r["log"])]
        L.extend("  %s: %s" % (s["runner"], s["line"]) for s in r["summary"])
        L.extend("  FAILED " + f for f in r["failures"])
        L.extend("  [%s] %s %s%s" % (c["status"], c.get("classname") or "", c["name"], (": " + c["message"][:160]) if c.get("message") else "")
                 for c in r["cases"][:80])
        L.append("----- last lines -----")
        L.append("\n".join(r["tail"].rstrip().split("\n")[-40:]))
        L.append("RUN_JSON=runs/%s.json" % r["id"])
        return "\n".join(L)
