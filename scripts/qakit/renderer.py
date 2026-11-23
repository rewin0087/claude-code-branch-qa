"""Renderer: validate qa.json and produce report.html, summary.md and ticket.md for one output folder."""
import glob
import os

from .errors import QAError
from .jsonio import load_json
from .report import ReportBuilder
from .snippets import SnippetCollector
from .summary import SummaryWriter, TicketFormats, file_url
from .tracelog import TraceLog
from .validator import QAValidator
from .workspace import Workspace


class RenderResult(object):
    def __init__(self, errors=(), warnings=(), report_path=None, summary=None):
        self.errors, self.warnings = list(errors), list(warnings)
        self.report_path, self.summary = report_path, summary

    @property
    def report_url(self):
        return file_url(self.report_path) if self.report_path else None


class Renderer(object):
    def __init__(self, out_dir):
        self.ws = Workspace.load(out_dir)
        self.qa = load_json(self.ws.path("qa.json"), "qa.json")
        self.notes = []

    def render(self, out_path=None):
        errors, warnings = QAValidator(self.qa, self.ws.repo, self.ws.out_dir).validate()
        if errors:
            return RenderResult(errors, warnings)
        impact = self.ws.optional_json("impact.json", self.notes.append)
        snippets = SnippetCollector(self.ws.repo).add_qa(self.qa, impact)
        traces = self._traces(snippets, warnings)
        out = os.path.abspath(out_path or self.ws.path("report.html"))
        summary = SummaryWriter(self.qa, self.ws.meta, out).write()
        formats = TicketFormats(self.qa, self.ws.meta)
        tooling = self.ws.optional_json("tooling.json", self.notes.append) or {}
        payload = {
            "meta": self.ws.meta, "qa": self.qa, "impact": impact, "traces": traces, "runs": self._runs(),
            "sources": snippets.build(), "ticket_text": self._ticket_text(),
            "tooling": {"stack": tooling.get("stack"), "frameworks": tooling.get("frameworks")},
            "formats": {"markdown": formats.markdown(), "jira": formats.jira(), "plain": formats.plain()},
            "summary_md": summary,
        }
        with open(out, "w") as fh:
            fh.write(ReportBuilder().build(payload))
        with open(self.ws.path("summary.md"), "w") as fh:
            fh.write(summary)
        with open(self.ws.path("ticket.md"), "w") if not os.path.exists(self.ws.path("ticket.md")) else \
                open(self.ws.path("ticket-comment.md"), "w") as fh:
            fh.write(payload["formats"]["markdown"])
        return RenderResult([], warnings, out, summary)

    def _ticket_text(self):
        p = self.ws.path("ticket.md")
        if os.path.exists(p):
            with open(p, errors="replace") as fh:
                return fh.read()[:20000]
        return None

    def _runs(self):
        """Everything under runs/: test-command results, http_check and ui_check results."""
        out = {}
        for p in sorted(glob.glob(self.ws.path("runs", "*.json"))):
            try:
                data = load_json(p)
            except QAError as e:
                self.notes.append(str(e))
                continue
            if isinstance(data, dict) and data.get("tail"):
                data = dict(data, tail=data["tail"][-6000:])
            out[os.path.relpath(p, self.ws.out_dir)] = data
        return out

    def _traces(self, snippets, warnings):
        traces = {}
        for sc in self.qa.get("scenarios") or []:
            if not sc.get("trace"):
                continue
            try:
                t = traces[sc["id"]] = TraceLog.load(self.ws.path(sc["trace"])).compact(limit=800)
            except QAError as e:
                warnings.append(str(e))
                continue
            for e in [e for e in t["events"] if e.get("file")][:300]:
                snippets.add(e.get("file"), e.get("line"))
        return traces
