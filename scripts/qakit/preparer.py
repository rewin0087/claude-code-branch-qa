"""Preparer: the branch under QA -> .branch-qa/<branch>/ with meta, changes, impact map and tooling.

Writes meta.json, changes.json (files + symbols), impact.json (layers, entry points, routes,
callers, covering tests, suggested test level per area) and tooling.json (stack, runners,
E2E tools, dev servers, tracers, database config). Prints a digest for the agent.
"""
import os
import re

from .dbconfig import DbConfigReader
from .diffparse import ChangedFile, DiffParser
from .errors import QAError
from .impact import ImpactAnalyzer
from .jsonio import write_json
from .stacks import StackDetector
from .ticket import TicketSource
from .tooling import DevServerFinder, E2EToolFinder, TestRunnerFinder
from .workspace import Workspace, slugify

SKIP_FILES = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Gemfile\.lock|poetry\.lock|Pipfile\.lock|composer\.lock|"
                        r"go\.sum|Cargo\.lock)$|\.(min\.js|map|snap|svg|png|jpe?g|gif|ico|pdf|woff2?)$|(^|/)(\.branch-qa|\.investigate|\.branch-review)/")
MAX_UNTRACKED_LINES = 4000


class PrepareOptions(object):
    def __init__(self, cwd, base=None, committed_only=False, ticket_ref=None, slug=None, paths=()):
        self.cwd, self.base, self.committed_only = cwd, base, committed_only
        self.ticket_ref, self.slug, self.paths = ticket_ref, slug, list(paths)


class Preparer(object):
    def __init__(self, opts):
        self.opts = opts
        self.ws = Workspace.for_path(opts.cwd)
        self.git = self.ws.git

    def run(self):
        branch = self.git.branch() or "HEAD"
        base, since = self._base(branch)
        changed = self._changed_files(since)
        if not changed:
            raise QAError("No changes between %s and the working tree on '%s': nothing to QA. "
                          "Pass --base <branch> if the base branch is a different one." % (base or "HEAD", branch))
        out = self.ws.create(self.opts.slug or slugify(branch))
        stack, frameworks = StackDetector(self.ws.repo, self.ws.files).detect()
        if not stack:
            stack = self._stack_from_extensions()
        runners = TestRunnerFinder(self.ws.repo, self.ws.files, stack, frameworks)
        e2e = E2EToolFinder(self.ws.repo, self.ws.files, frameworks).find()
        has_browser = any(t["kind"] == "project" and t["tool"] in ("playwright", "cypress", "capybara", "selenium") or
                          t["tool"] == "ui_check.py" and t["available"] for t in e2e)
        impact = ImpactAnalyzer(self.ws, changed, has_browser).analyze()
        servers = DevServerFinder(self.ws.repo, self.ws.files, frameworks)
        tooling = {"stack": stack, "frameworks": frameworks, "test_runners": runners.runners(), "tracers": runners.tracers(),
                   "e2e": e2e, "dev_servers": servers.commands(), "listening": servers.listening(),
                   "django_settings": runners.django_settings(),
                   "database": DbConfigReader(self.ws.repo, self.ws.files).read()}
        commits = self.git.commits(since) if since else []
        ticket = TicketSource(self.opts.ticket_ref, self.ws.repo, self.git.remote_web_url())
        meta = self.ws.write_meta({
            "branch": branch, "base": base, "merge_base": since, "sha": self.git.head_sha(),
            "remote": self.git.remote_web_url(), "uncommitted_included": not self.opts.committed_only,
            "commits": commits, "ticket_ref": {"kind": ticket.kind(), "text": (self.opts.ticket_ref or "")[:300],
                                               "fetch": ticket.fetch_hint()}})
        write_json(self.ws.path("changes.json"), [c.to_dict(self.ws_source(c.path)) for c in changed])
        write_json(self.ws.path("impact.json"), impact)
        write_json(self.ws.path("tooling.json"), tooling)
        return meta, impact, tooling

    def _stack_from_extensions(self):
        """No manifest (requirements.txt, Gemfile, package.json...): guess from file extensions."""
        ext = {".py": "python", ".rb": "ruby", ".js": "javascript", ".ts": "javascript", ".go": "go", ".php": "php",
               ".java": "jvm", ".kt": "jvm", ".cs": "dotnet"}
        counts = {}
        for f in self.ws.files:
            lang = ext.get(os.path.splitext(f)[1])
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:2]

    def ws_source(self, rel):
        text = self.ws.read_text(rel)
        return text.split("\n") if text is not None else None

    def _base(self, branch):
        if self.opts.base:
            base = self.git.resolve_ref(self.opts.base)
            if not base:
                raise QAError("Base branch '%s' not found." % self.opts.base)
        else:
            base = self.git.detect_base(branch)
        if not base:      # on the base branch itself (or no base): QA the uncommitted work against HEAD
            return None, "HEAD" if self.git.run(["rev-parse", "--verify", "--quiet", "HEAD"], check=False) else None
        return base, self.git.merge_base(base)

    def _changed_files(self, since):
        files = []
        if since:
            files = DiffParser().parse(self.git.diff(since, uncommitted=not self.opts.committed_only))
        if not self.opts.committed_only:
            known = {f.path for f in files}
            for rel in self.git.untracked():
                if rel not in known and not SKIP_FILES.search(rel):
                    files.append(self._untracked(rel))
        files = [f for f in files if f and not SKIP_FILES.search(f.path)]
        if self.opts.paths:
            files = [f for f in files if any(f.path == p or f.path.startswith(p.rstrip("/") + "/") for p in self.opts.paths)]
        return files

    def _untracked(self, rel):
        text = self.ws.read_text(rel)
        if text is None or "\0" in text[:4000]:
            return None
        cf = ChangedFile(rel, status="added")
        lines = text.split("\n")[:MAX_UNTRACKED_LINES]
        cf.added = list(range(1, len(lines) + 1))
        cf.added_text = lines
        return cf


class PrepareDigest(object):
    """What the agent reads after prepare.py: the change, its reach, and how to test it."""

    def __init__(self, meta, impact, tooling):
        self.meta, self.impact, self.tooling = meta, impact, tooling

    def format(self):
        m, imp, t = self.meta, self.impact, self.tooling
        L = ["OUT_DIR=%s" % m["out_dir"], "REPO=%s" % m["repo"],
             "Branch: %s  (base %s, merge-base %s, head %s%s)" % (m["branch"], m["base"] or "none", (m["merge_base"] or "")[:10],
                                                               m["sha"], ", uncommitted work included" if m["uncommitted_included"] else ""),
             "Stack: %s | %s" % (", ".join(t["stack"]) or "unknown", ", ".join(t["frameworks"]) or "no frameworks detected")]
        if m["commits"]:
            L.append("\nCommits (%d):" % len(m["commits"]))
            L.extend("  %s %s" % (c["short"], c["subject"][:100]) for c in m["commits"][:15])
        tr = m.get("ticket_ref") or {}
        L.append("\nTicket: %s" % ({"none": "none given (derive expected behaviour from the code, commits and tests; say so in caveats)",
                                    "text": "inline text: write it verbatim to <OUT_DIR>/ticket.md, then run ticket.py",
                                    "file": "file %s: run ticket.py --file %s" % (tr.get("text"), tr.get("text")),
                                    }.get(tr.get("kind")) or "%s %s: fetch with %s, save to <OUT_DIR>/ticket.md, run ticket.py"
                                    % (tr.get("kind"), tr.get("text"), tr.get("fetch"))))
        L.append("\nChanged areas (%d files):" % len(imp["areas"]))
        for a in imp["areas"]:
            L.append("  %s %-10s %-10s %s (+%d -%d)%s" % (a["id"], a["layer"], a["test_level"], a["path"], a["additions"], a["deletions"],
                                                     "  symbols: " + ", ".join(a["symbols"][:6]) if a["symbols"] else ""))
            if a["layer"] in ("docs", "test", "style"):
                continue
            L.append("       why: " + a["reason"])
            for key, label in (("external_http", "external HTTP"), ("async_job", "async/background"), ("callback", "callbacks/events"),
                               ("validation", "validation"), ("db_write", "DB writes"), ("transaction", "transactions/locks"),
                               ("auth", "auth"), ("form", "form"), ("frontend_api_call", "calls API"), ("mail", "mail"),
                               ("feature_flag", "feature flag")):
                if a["signals"].get(key):
                    L.append("       %s: %s" % (label, a["signals"][key][0][:110]))
            for c in a.get("api_calls", [])[:3]:
                L.append("       UI → API: %s %s" % (c["method"] or "?", c["path"]))
            for r in a.get("routes", [])[:4]:
                L.append("       route: %s %s  (%s:%s)" % (r.get("method"), r.get("path"), r.get("file"), r.get("line")))
            for e in a.get("entry_points", [])[:5]:
                L.append("       reached from %s %s:%s via %s" % (e["layer"], e["file"], e["line"], e["via"]))
            if a.get("callers"):
                L.append("       callers: " + ", ".join("%s:%s" % (c["file"], c["line"]) for c in a["callers"][:6]))
            L.append("       existing tests: " + (", ".join(sorted({c["file"] for c in a["covering_tests"]})[:6]) or "none found"))
        if imp["new_routes"]:
            L.append("\nNew/changed routes:")
            L.extend("  %s %s → %s  (%s:%s)" % (r["method"], r["path"], r.get("handler") or "", r["file"], r["line"]) for r in imp["new_routes"])
        if imp["tests_changed"]:
            L.append("\nTests changed on the branch: " + ", ".join(imp["tests_changed"][:15]))
        L.append("\nSuggested test levels: " + ", ".join("%s ×%d" % kv for kv in sorted(imp["levels"].items())))
        L.append("\nTest runners:")
        L.extend(["  %-9s %s %s" % (r["runner"], r["env"], r["cmd"]) for r in t["test_runners"]] or ["  none detected"])
        L.append("E2E / browser:")
        for e in t["e2e"]:
            L.append("  %-12s %s%s" % (e["tool"], e["cmd"], ("  (" + e["note"] + ")") if e.get("note") else ""))
        L.append("Dev server: " + ("; ".join(s["cmd"] for s in t["dev_servers"]) or "none detected"))
        L.append("Ports answering on localhost now (may be unrelated apps; confirm before using): " +
                 (", ".join(t["listening"]) or "none of the usual ports"))
        L.append("Tracers:")
        L.extend(["  " + x["cmd"] for x in t["tracers"]] or ["  none for this stack (pin-point the code path by reading + test output)"])
        db = t["database"]
        L.append("Database config (redacted): " + ("; ".join("%s[%s] %s=%s" % (s["file"], s["env"], s["key"], s["value"])
                                                            for s in db["settings"][:6]) or "none found"))
        L.append("\nFiles: meta.json changes.json impact.json tooling.json in OUT_DIR")
        return "\n".join(L)
