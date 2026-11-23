"""Preparer: the branch under QA -> .branch-qa/<branch>/ with meta, changes, impact map and tooling.

Writes meta.json, changes.json (files + symbols), impact.json (layers, entry points, routes,
callers, covering tests, suggested test level per area) and tooling.json (stack, runners,
E2E tools, dev servers, tracers, database config). PrepareDigest prints what the agent reads.

  branchchanges.py  BranchChanges   base branch, merge-base, changed + untracked files
  impact.py         ImpactAnalyzer  what the changes reach and how to test them
  tooling.py        ToolingSurvey   how this project can be exercised
  ticket.py         TicketSource    what kind of ticket reference the user gave
"""
from .branchchanges import BranchChanges
from .errors import QAError
from .impact import ImpactAnalyzer
from .jsonio import JsonFile
from .text import Text
from .ticket import TicketSource
from .tooling import ToolingSurvey
from .workspace import Workspace


class PrepareOptions(object):
    def __init__(self, cwd, base=None, committed_only=False, ticket_ref=None, slug=None, paths=()):
        self.cwd, self.base, self.committed_only = cwd, base, committed_only
        self.ticket_ref, self.slug, self.paths = ticket_ref, slug, list(paths)


class Preparer(object):
    def __init__(self, opts):
        self.opts = opts
        self.ws = Workspace.for_path(opts.cwd)
        self.git = self.ws.git
        self.changes = BranchChanges(self.ws, opts.base, opts.committed_only, opts.paths)

    def run(self):
        branch = self.git.branch() or "HEAD"
        base, since = self.changes.base(branch)
        changed = self.changes.files(since)
        if not changed:
            raise QAError("No changes between %s and the working tree on '%s': nothing to QA. "
                          "Pass --base <branch> if the base branch is a different one." % (base or "HEAD", branch))
        self.ws.create(self.opts.slug or Text.slugify(branch))
        survey = ToolingSurvey(self.ws.repo, self.ws.files)
        tooling = survey.collect()
        impact = ImpactAnalyzer(self.ws, changed, survey.has_browser_tooling(tooling)).analyze()
        meta = self.ws.write_meta(self._meta(branch, base, since))
        JsonFile.write(self.ws.path("changes.json"), [c.to_dict(self.changes.source_lines(c.path)) for c in changed])
        JsonFile.write(self.ws.path("impact.json"), impact)
        JsonFile.write(self.ws.path("tooling.json"), tooling)
        return meta, impact, tooling

    def _meta(self, branch, base, since):
        ticket = TicketSource(self.opts.ticket_ref, self.ws.repo, self.git.remote_web_url())
        return {"branch": branch, "base": base, "merge_base": since, "sha": self.git.head_sha(),
                "remote": self.git.remote_web_url(), "uncommitted_included": not self.opts.committed_only,
                "commits": self.git.commits(since) if since else [],
                "ticket_ref": {"kind": ticket.kind(), "text": (self.opts.ticket_ref or "")[:300], "fetch": ticket.fetch_hint()}}


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
