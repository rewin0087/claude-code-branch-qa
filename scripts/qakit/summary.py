"""The results table, in the formats people paste it: the chat summary, Markdown, Jira wiki and plain text.

ResultRows      scenarios -> rows (#, test, type, result, expected?, remarks), shared by every format
SummaryWriter   the markdown reply for the Claude Code chat (table + conclusion + failures + caveats + link)
TicketFormats   what the report's "Copy for the ticket" section offers: markdown, jira, plain
"""
import os
import re

from . import vocabulary as V


def file_url(path):
    return "file://" + os.path.abspath(path).replace(" ", "%20")


def one_line(text, limit=None):
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if not limit or len(s) <= limit else s[:limit - 1] + "…"


class ResultRows(object):
    HEAD = ("#", "Test scenario", "Type", "Result", "Expected?", "Remarks")

    def __init__(self, qa):
        self.qa = qa

    def rows(self, remark_limit=None):
        out = []
        for sc in self.qa.get("scenarios") or []:
            out.append((sc.get("id", ""), one_line(sc.get("title")), V.TYPES.get(sc.get("type"), sc.get("type") or ""),
                        V.RESULTS.get(sc.get("result"), sc.get("result") or ""), V.AS_EXPECTED[V.as_expected(sc)],
                        one_line(sc.get("remarks"), remark_limit)))
        return out

    def counts(self):
        res = [s.get("result") for s in self.qa.get("scenarios") or []]
        return {k: res.count(k) for k in V.RESULTS if res.count(k)}

    def counts_text(self):
        c = self.counts()
        total = sum(c.values())
        return "%d scenario%s: %s" % (total, "" if total == 1 else "s",
                                      ", ".join("%d %s" % (n, k.replace("_", " ")) for k, n in c.items()) or "none")


def md_cell(s):
    return str(s).replace("\\", "\\\\").replace("|", "\\|")


def md_table(head, rows):
    L = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    L.extend("| " + " | ".join(md_cell(c) for c in r) + " |" for r in rows)
    return "\n".join(L)


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
        L = ["**QA result: %s**: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), one_line(s.get("headline"))),
             "", self.context_line() + " · " + self.rows.counts_text(), "",
             md_table(ResultRows.HEAD, self.rows.rows())]
        if s.get("conclusion"):
            L += ["", "**Conclusion:** " + one_line(s["conclusion"])]
        L += self._lists(lambda x: "- " + x)
        return "\n".join(L)

    def jira(self):
        s = self.qa.get("summary") or {}

        def cell(x):
            s = str(x).replace("|", "\\|").replace("{", "\\{").replace("}", "\\}")
            return re.sub(r"`([^`]+)`", r"{{\1}}", s) or " "
        L = ["*QA result: %s*: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), one_line(s.get("headline"))), "",
             self.context_line().replace("`", "") + " · " + self.rows.counts_text(), "",
             "||" + "||".join(ResultRows.HEAD) + "||"]
        L.extend("|" + "|".join(cell(c) for c in r) + "|" for r in self.rows.rows())
        if s.get("conclusion"):
            L += ["", "*Conclusion:* " + one_line(s["conclusion"])]
        L += self._lists(lambda x: "* " + x, bold=lambda x: "*%s*" % x)
        L = [re.sub(r"`([^`]+)`", r"{{\1}}", l) if not l.startswith("|") else l for l in L]
        return "\n".join(L)

    def plain(self):
        s = self.qa.get("summary") or {}
        rows = self.rows.rows()
        widths = [min(60, max(len(str(r[i])) for r in rows + [ResultRows.HEAD])) for i in range(len(ResultRows.HEAD) - 1)]

        def line(r):
            return "  ".join(one_line(c, w).ljust(w) for c, w in zip(r[:-1], widths)) + "  " + str(r[-1])
        L = ["QA result: %s: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), one_line(s.get("headline"))),
             self.context_line().replace("`", "") + " · " + self.rows.counts_text(), "", line(ResultRows.HEAD)]
        L.extend(line(r) for r in rows)
        if s.get("conclusion"):
            L += ["", "Conclusion: " + one_line(s["conclusion"])]
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
                L.append(bullet("%s %s: %s%s" % (sc["id"], one_line(sc.get("title")), one_line(reason),
                                                 (" Fix: " + one_line(fix)) if fix else "")))
        if self.qa.get("caveats"):
            L += ["", bold("Caveats:")] + [bullet(one_line(c)) for c in self.qa["caveats"]]
        if self.qa.get("not_covered"):
            L += ["", bold("Not covered:")] + [bullet(one_line(c)) for c in self.qa["not_covered"]]
        return L


class SummaryWriter(object):
    """The reply relayed in the chat."""

    def __init__(self, qa, meta, report_path):
        self.qa, self.meta, self.report_path = qa, meta, report_path

    def write(self):
        qa, s = self.qa, self.qa.get("summary") or {}
        rows = ResultRows(qa)
        L = ["## QA: %s" % one_line(qa.get("title")), "",
             "**%s**: %s" % (V.VERDICTS.get(s.get("verdict"), s.get("verdict")), one_line(s.get("headline"))), "",
             TicketFormats(qa, self.meta).context_line() + " · " + rows.counts_text(), "",
             md_table(ResultRows.HEAD, rows.rows(remark_limit=220))]
        reqs = qa.get("requirements") or []
        if reqs:
            scs = qa.get("scenarios") or []
            st = [V.requirement_status(r, scs) for r in reqs]
            L += ["", "**Requirements:** " + ", ".join("%d %s" % (st.count(k), V.REQ_STATUS[k].split(" ", 1)[1].lower())
                                                       for k in V.REQ_STATUS if st.count(k))]
        if s.get("conclusion"):
            L += ["", "**Conclusion:** " + one_line(s["conclusion"])]
        failed = [sc for sc in qa.get("scenarios") or [] if sc.get("result") == "failed"]
        if failed:
            L += ["", "**Failed, and how to fix:**"]
            for sc in failed:
                f, fix = sc.get("failure") or {}, sc.get("fix") or {}
                where = " (`%s:%s`)" % (f["file"], f.get("line")) if f.get("file") else ""
                L.append("- **%s %s**: %s%s%s" % (sc["id"], one_line(sc.get("title")), one_line(f.get("reason") or sc.get("remarks")),
                                                where, (" **Fix:** " + one_line(fix["description"])) if fix.get("description") else ""))
        blocked = [sc for sc in qa.get("scenarios") or [] if sc.get("result") in ("blocked", "not_run")]
        if blocked:
            L += ["", "**Not run:** " + "; ".join("%s %s" % (sc["id"], one_line(sc.get("remarks"), 120)) for sc in blocked)]
        if qa.get("caveats"):
            L += ["", "**Caveats:**"] + ["- " + one_line(c) for c in qa["caveats"]]
        L += ["", "Report: %s" % file_url(self.report_path),
              "Use **Copy for the ticket** in the report to paste this table into the ticket (Markdown, Jira or plain text)."]
        return "\n".join(L)
