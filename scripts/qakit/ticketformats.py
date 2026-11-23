"""TicketFormats: the results table, conclusion, failures and caveats as people paste them into a ticket:
Markdown (GitHub / GitLab / Linear), Jira wiki markup and plain text. (The rich HTML table is built
in the report page itself.)"""
import re

from . import vocabulary as V
from .results import ResultRows
from .text import MarkdownTable, Text


class TicketFormats(object):
    def __init__(self, qa, meta):
        self.qa, self.meta = qa, meta
        self.rows = ResultRows(qa)

    def context_line(self):
        m, t = self.meta, self.qa.get("ticket") or {}
        env = (self.qa.get("environment") or {}).get("env")
        bits = ["Branch `%s` @ `%s`" % (m.get("branch"), m.get("sha"))]
        if m.get("base"):
            bits.append("vs `%s`" % m["base"])
        if env:
            bits.append("env: %s" % env)
        if t.get("id"):
            bits.append("ticket %s" % t["id"])
        return " · ".join(bits)

    def markdown(self):
        s = self.qa.get("summary") or {}
        L = ["**QA result: %s**: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), Text.one_line(s.get("headline"))),
             "", self.context_line() + " · " + self.rows.counts_text(), "",
             MarkdownTable(ResultRows.HEAD, self.rows.rows()).render()]
        if s.get("conclusion"):
            L += ["", "**Conclusion:** " + Text.one_line(s["conclusion"])]
        L += self._lists(lambda x: "- " + x)
        return "\n".join(L)

    def jira(self):
        s = self.qa.get("summary") or {}

        def cell(x):
            s = str(x).replace("|", "\\|").replace("{", "\\{").replace("}", "\\}")
            return re.sub(r"`([^`]+)`", r"{{\1}}", s) or " "
        L = ["*QA result: %s*: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), Text.one_line(s.get("headline"))), "",
             self.context_line().replace("`", "") + " · " + self.rows.counts_text(), "",
             "||" + "||".join(ResultRows.HEAD) + "||"]
        L.extend("|" + "|".join(cell(c) for c in r) + "|" for r in self.rows.rows())
        if s.get("conclusion"):
            L += ["", "*Conclusion:* " + Text.one_line(s["conclusion"])]
        L += self._lists(lambda x: "* " + x, bold=lambda x: "*%s*" % x)
        L = [re.sub(r"`([^`]+)`", r"{{\1}}", l) if not l.startswith("|") else l for l in L]
        return "\n".join(L)

    def plain(self):
        s = self.qa.get("summary") or {}
        rows = self.rows.rows()
        widths = [min(60, max(len(str(r[i])) for r in rows + [ResultRows.HEAD])) for i in range(len(ResultRows.HEAD) - 1)]

        def line(r):
            return "  ".join(Text.one_line(c, w).ljust(w) for c, w in zip(r[:-1], widths)) + "  " + str(r[-1])
        L = ["QA result: %s: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), Text.one_line(s.get("headline"))),
             self.context_line().replace("`", "") + " · " + self.rows.counts_text(), "", line(ResultRows.HEAD)]
        L.extend(line(r) for r in rows)
        if s.get("conclusion"):
            L += ["", "Conclusion: " + Text.one_line(s["conclusion"])]
        L += self._lists(lambda x: "- " + x, bold=lambda x: x)
        return "\n".join(L)

    def _lists(self, bullet, bold=lambda x: "**%s**" % x):
        L = []
        failed = [sc for sc in self.qa.get("scenarios") or [] if sc.get("result") == "failed"]
        if failed:
            L += ["", bold("Failed scenarios and suggested fixes:")]
            for sc in failed:
                fix = (sc.get("fix") or {}).get("description")
                reason = (sc.get("failure") or {}).get("reason") or sc.get("remarks")
                L.append(bullet("%s %s: %s%s" % (sc["id"], Text.one_line(sc.get("title")), Text.one_line(reason),
                                                 (" Fix: " + Text.one_line(fix)) if fix else "")))
        if self.qa.get("caveats"):
            L += ["", bold("Caveats:")] + [bullet(Text.one_line(c)) for c in self.qa["caveats"]]
        if self.qa.get("not_covered"):
            L += ["", bold("Not covered:")] + [bullet(Text.one_line(c)) for c in self.qa["not_covered"]]
        return L
