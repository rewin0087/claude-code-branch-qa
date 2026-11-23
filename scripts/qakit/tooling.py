"""How this project can be exercised: test runners, E2E/browser tooling, dev servers, tracers.

TestRunnerFinder   how to run one test file under the test environment (rspec, pytest, jest, ...)
E2EToolFinder      Playwright / Cypress / Capybara system tests / Selenium / Python Playwright
DevServerFinder    how the app starts locally, and which local ports already answer
Nothing is executed except a TCP connect to localhost ports and `import` probes.
"""
import json
import os
import re
import shutil
import socket
import subprocess

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
COMMON_PORTS = (3000, 3001, 4000, 4200, 5000, 5173, 8000, 8080, 8888, 9000)
JS_RUNNERS = (("Vitest", "npx vitest run <file>"), ("Jest", "npx jest <file> --runTestsByPath"), ("Mocha", "npx mocha <file>"))
OTHER_RUNNERS = {
    "go": {"stack": "go", "runner": "go test", "cmd": "go test ./<pkg> -run <TestName> -v", "env": ""},
    "php": {"stack": "php", "runner": "phpunit", "cmd": "vendor/bin/phpunit <file>", "env": "APP_ENV=testing"},
    "jvm": {"stack": "jvm", "runner": "gradle/maven", "cmd": "./gradlew test --tests <Class>  |  mvn -Dtest=<Class> test", "env": ""},
    "dotnet": {"stack": "dotnet", "runner": "dotnet test", "cmd": "dotnet test --filter <Name>", "env": ""},
}


class TestRunnerFinder(object):
    def __init__(self, repo, files, stack, frameworks):
        self.repo, self.files, self.fs = repo, files, set(files)
        self.stack, self.frameworks = stack, frameworks

    def python(self):
        """The project's interpreter: a venv inside the repo when there is one."""
        venv = next((os.path.join(self.repo, c) for c in (".venv/bin/python", "venv/bin/python", "env/bin/python")
                     if os.path.exists(os.path.join(self.repo, c))), None)
        return venv or shutil.which("python3") or "python3"

    def runners(self):
        cmds = []
        if "RSpec" in self.frameworks or any(f.startswith("spec/") and f.endswith("_spec.rb") for f in self.files):
            cmds.append({"stack": "ruby", "runner": "rspec", "cmd": "bundle exec rspec <file>[:line]", "env": "RAILS_ENV=test",
                         "junit": "--format RspecJunitFormatter --out <junit.xml> (if the gem is present)"})
        if "test/test_helper.rb" in self.fs:
            cmds.append({"stack": "ruby", "runner": "minitest", "cmd": "bin/rails test <file>[:line]", "env": "RAILS_ENV=test"})
        if "python" in self.stack:
            if "pytest" in self.frameworks or "pytest.ini" in self.fs or any(f.endswith("conftest.py") for f in self.files):
                cmds.append({"stack": "python", "runner": "pytest", "cmd": "%s -m pytest <file>::<test> -q" % self.python(),
                             "env": "", "junit": "--junitxml=<junit.xml>"})
            elif "Django" in self.frameworks:
                cmds.append({"stack": "python", "runner": "django", "cmd": "%s manage.py test <dotted.path> -v 2" % self.python(), "env": ""})
            else:
                cmds.append({"stack": "python", "runner": "unittest", "cmd": "%s -m unittest <module> -v" % self.python(), "env": ""})
        for fw, cmd in JS_RUNNERS:
            if fw in self.frameworks:
                cmds.append({"stack": "javascript", "runner": fw.lower(), "cmd": cmd, "env": "NODE_ENV=test",
                             "junit": "--reporter=junit --outputFile=<junit.xml>" if fw == "Vitest" else ""})
        cmds.extend(OTHER_RUNNERS[s] for s in ("go", "php", "jvm", "dotnet") if s in self.stack)
        return cmds

    def django_settings(self):
        try:
            with open(os.path.join(self.repo, "manage.py"), errors="replace") as fh:
                m = re.search(r"DJANGO_SETTINGS_MODULE['\"],\s*['\"]([\w.]+)['\"]", fh.read())
                return m.group(1) if m else None
        except OSError:
            return None

    def tracers(self):
        out = []
        if "python" in self.stack:
            out.append({"stack": "python", "interpreter": self.python(),
                        "cmd": "%s %s --root %s --env test --out <OUT_DIR>/trace/<T>.json -- <harness.py | -m pytest file>"
                               % (self.python(), os.path.join(SCRIPTS_DIR, "trace_py.py"), self.repo)})
        if "ruby" in self.stack:
            out.append({"stack": "ruby", "interpreter": shutil.which("ruby") or "ruby",
                        "cmd": "TRACE_AUTOSTART=1 TRACE_OUT=<OUT_DIR>/trace/<T>.json TRACE_ROOT=%s RUBYOPT=\"-r%s\" "
                               "RAILS_ENV=test bundle exec rspec <spec>" % (self.repo, os.path.join(SCRIPTS_DIR, "trace_rb.rb"))})
        return out


class E2EToolFinder(object):
    """Browser / end-to-end tooling the project already has, or that is available on this machine."""

    def __init__(self, repo, files, frameworks):
        self.repo, self.files, self.fs, self.frameworks = repo, files, set(files), frameworks

    def find(self):
        tools = []
        cfg = [f for f in self.files if re.search(r"(^|/)playwright\.config\.[cm]?[jt]s$", f)]
        if cfg or "Playwright" in self.frameworks:
            tools.append({"tool": "playwright", "kind": "project", "config": cfg[0] if cfg else None,
                          "cmd": "npx playwright test <spec> --reporter=list,junit",
                          "note": "write the throwaway spec under the config's testDir or pass --config with a temp config"})
        cfg = [f for f in self.files if re.search(r"(^|/)cypress\.config\.[cm]?[jt]s$|(^|/)cypress\.json$", f)]
        if cfg or "Cypress" in self.frameworks:
            tools.append({"tool": "cypress", "kind": "project", "config": cfg[0] if cfg else None,
                          "cmd": "npx cypress run --spec <spec> --headless"})
        if any(f.startswith(("spec/system/", "spec/features/", "test/system/")) for f in self.files) or \
                "capybara" in self._read("Gemfile").lower():
            tools.append({"tool": "capybara", "kind": "project", "config": None,
                          "cmd": "RAILS_ENV=test bundle exec rspec spec/system/<spec>.rb  |  bin/rails test:system",
                          "note": "headless Chrome via selenium/cuprite, as the project's driven_by sets"})
        if "selenium" in (self._read("requirements.txt") + self._read("pyproject.toml")).lower():
            tools.append({"tool": "selenium", "kind": "project", "config": None, "cmd": "pytest <file>"})
        pw = self._python_playwright()
        tools.append({"tool": "ui_check.py", "kind": "skill", "available": bool(pw["module"]),
                      "browser": pw["browser"],
                      "cmd": "%s %s --dir <OUT_DIR> --spec <OUT_DIR>/tests/ui.json" % (pw["python"], os.path.join(SCRIPTS_DIR, "ui_check.py")),
                      "note": "headless Chromium/Chrome via Python Playwright" + (
                          "" if pw["module"] else ": not installed here (ask the user before `pip install playwright`)")})
        return tools

    def _read(self, rel):
        try:
            with open(os.path.join(self.repo, rel), errors="replace") as fh:
                return fh.read(200000)
        except OSError:
            return ""

    @staticmethod
    def _python_playwright():
        py = shutil.which("python3") or "python3"
        try:
            ok = subprocess.run([py, "-c", "import playwright"], capture_output=True, timeout=20).returncode == 0
        except Exception:      # noqa
            ok = False
        chrome = next((p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                                   shutil.which("google-chrome") or "", shutil.which("chromium") or "",
                                   shutil.which("chromium-browser") or "") if p and os.path.exists(p)), None)
        return {"python": py, "module": ok, "browser": "chrome" if chrome else None}


class DevServerFinder(object):
    def __init__(self, repo, files, frameworks):
        self.repo, self.fs, self.frameworks = repo, set(files), frameworks

    def commands(self):
        out = []
        pkg = self._package_scripts()
        for name in ("dev", "start", "serve", "start:dev"):
            if name in pkg:
                out.append({"cmd": "npm run %s" % name, "source": "package.json", "detail": pkg[name][:120]})
        if "bin/dev" in self.fs:
            out.append({"cmd": "bin/dev", "source": "bin/dev", "detail": "Procfile.dev processes"})
        if "Rails" in self.frameworks:
            out.append({"cmd": "bin/rails server -p 3000", "source": "Rails", "detail": "RAILS_ENV=development by default"})
        if "manage.py" in self.fs:
            out.append({"cmd": "python manage.py runserver 8000", "source": "Django", "detail": ""})
        if "FastAPI" in self.frameworks:
            out.append({"cmd": "uvicorn <module>:app --port 8000", "source": "FastAPI", "detail": ""})
        if "Flask" in self.frameworks:
            out.append({"cmd": "flask --app <module> run -p 5000", "source": "Flask", "detail": ""})
        for f in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            if f in self.fs:
                out.append({"cmd": "docker compose up", "source": f, "detail": ""})
        return out

    def _package_scripts(self):
        try:
            with open(os.path.join(self.repo, "package.json")) as fh:
                return json.load(fh).get("scripts") or {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def listening(ports=COMMON_PORTS, timeout=0.15):
        """Local ports that accept a TCP connection right now (a running dev server, maybe)."""
        up = []
        for p in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                if s.connect_ex(("127.0.0.1", p)) == 0:
                    up.append("http://localhost:%d" % p)
            finally:
                s.close()
        return up
