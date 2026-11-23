"""SummaryWriter: the markdown reply relayed in the Claude Code chat (verdict, results table,
requirements tally, conclusion, failures with fixes, caveats, report link)."""
from . import vocabulary as V
from .results import ResultRows
from .text import MarkdownTable, Text
from .ticketformats import TicketFormats
from .vocabulary import Outcomes


class SummaryWriter(object):
    """The reply relayed in the chat."""

    def __init__(self, qa, meta, report_path):
        self.qa, self.meta, self.report_path = qa, meta, report_path

    def write(self):
        qa, s = self.qa, self.qa.get("summary") or {}
        rows = ResultRows(qa)
        L = ["## QA: %s" % Text.one_line(qa.get("title")), "",
             "**%s**: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), Text.one_line(s.get("headline"))), "",
             TicketFormats(qa, self.meta).context_line() + " · " + rows.counts_text(), "",
             MarkdownTable(ResultRows.HEAD, rows.rows(remark_limit=220)).render()]
        reqs = qa.get("requirements") or []
        if reqs:
            scs = qa.get("scenarios") or []
            st = [Outcomes.requirement_status(r, scs) for r in reqs]
            L += ["", "**Requirements:** " + ", ".join("%d %s" % (st.count(k), V.REQ_STATUS[k].split(" ", 1)[1].lower())
                                                       for k in V.REQ_STATUS if st.count(k))]
        if s.get("conclusion"):
            L += ["", "**Conclusion:** " + Text.one_line(s["conclusion"])]
        failed = [sc for sc in qa.get("scenarios") or [] if sc.get("result") == "failed"]
        if failed:
            L += ["", "**Failed, and how to fix:**"]
            for sc in failed:
                f, fix = sc.get("failure") or {}, sc.get("fix") or {}
                where = " (`%s:%s`)" % (f["file"], f.get("line")) if f.get("file") else ""
                L.append("- **%s %s**: %s%s%s" % (sc["id"], Text.one_line(sc.get("title")), Text.one_line(f.get("reason") or sc.get("remarks")),
                                                where, (" **Fix:** " + Text.one_line(fix["description"])) if fix.get("description") else ""))
        blocked = [sc for sc in qa.get("scenarios") or [] if sc.get("result") in ("blocked", "not_run")]
        if blocked:
            L += ["", "**Not run:** " + "; ".join("%s %s" % (sc["id"], Text.one_line(sc.get("remarks"), 120)) for sc in blocked)]
        if qa.get("caveats"):
            L += ["", "**Caveats:**"] + ["- " + Text.one_line(c) for c in qa["caveats"]]
        L += ["", "Report: %s" % Text.file_url(self.report_path),
              "Use **Copy for the ticket** in the report to paste this table into the ticket (Markdown, Jira or plain text)."]
        return "\n".join(L)
