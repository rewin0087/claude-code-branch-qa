"""The ticket the branch implements: where it comes from, and the requirements inside it.

TicketSource   what the user gave: inline text, a file, a URL, or an issue number like #123 / ABC-123
TicketParser   ticket text -> id, title, acceptance criteria / requirements (R1, R2, ...)

Fetching a ticket from a tracker is left to the agent (gh / glab / an MCP connector / WebFetch):
TicketSource only says which tool fits. Requirements found here are a starting point; the agent
refines them in qa.json.
"""
import os
import re

TICKET_ID = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b|(?:^|\s)#(\d+)\b")
AC_HEADING = re.compile(r"^\s*(?:#+\s*|\*\*|__)?\s*(acceptance\s+criteria|ac|requirements?|expected\s+(?:behaviou?r|results?)"
                        r"|definition\s+of\s+done|dod|scenarios?|test\s+cases?|success\s+criteria|rules?)\b.*$", re.I)
OTHER_HEADING = re.compile(r"^\s*(?:#+\s+\S|\*\*[^*]+\*\*\s*:?\s*$|[A-Z][\w /&-]{2,40}:\s*$)")
HEADING_WORD = re.compile(r"^.*?(criteria|requirements?|done|dod|scenarios?|cases?|rules?|results?|behaviou?r)\b[*_:\s-]*", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|\[[ xX]\]|[-*]\s+\[[ xX]\])\s+(.*\S)")
GHERKIN = re.compile(r"^\s*(given|when|then|and|but)\b\s+(.*)", re.I)
REQ_WORDS = re.compile(r"\b(must|should|shall|cannot|can't|can not|only|never|always|required?|reject|allow|prevent|"
                       r"validate|return|display|show|error|fail|limit|exceed|when|if)\b", re.I)


class TicketSource(object):
    """Classifies the ticket reference the user typed after /qa."""

    def __init__(self, text, repo=None, remote_web=None):
        self.text, self.repo, self.remote_web = (text or "").strip(), repo, remote_web or ""

    def kind(self):
        t = self.text
        if not t:
            return "none"
        if re.match(r"^https?://\S+$", t):
            return "url"
        if self.repo and "\n" not in t and len(t) < 300 and os.path.isfile(os.path.join(self.repo, t) if not os.path.isabs(t) else t):
            return "file"
        if re.match(r"^(#\d+|[A-Z][A-Z0-9]{1,9}-\d+)$", t):
            return "issue"
        return "text"

    def fetch_hint(self):
        """How the agent can fetch a referenced ticket (it is never fetched here)."""
        t, k = self.text, self.kind()
        if k == "issue" and t.startswith("#"):
            if "github.com" in self.remote_web:
                return "gh issue view %s --comments" % t[1:]
            if "gitlab" in self.remote_web:
                return "glab issue view %s --comments" % t[1:]
            return "the project's issue tracker (gh / glab) for issue %s" % t
        if k == "issue":
            return "the Jira/Linear connector (or ask the user to paste the ticket) for %s" % t
        if k == "url":
            if "github.com" in t and "/issues/" in t:
                return "gh issue view %s --comments" % t
            if "/-/issues/" in t:
                return "glab issue view %s --comments" % t
            if "github.com" in t and "/pull/" in t:
                return "gh pr view %s --comments" % t
            if "/-/merge_requests/" in t:
                return "glab mr view %s --comments" % t
            return "WebFetch %s (or a connected tracker tool); ask the user to paste it if it needs a login" % t
        return None


class TicketParser(object):
    def __init__(self, text):
        self.text = (text or "").replace("\r\n", "\n")

    def parse(self):
        lines = self.text.split("\n")
        return {"id": self.ticket_id(), "title": self.title(lines), "requirements": self.requirements(lines),
                "chars": len(self.text)}

    def ticket_id(self):
        m = TICKET_ID.search(self.text)
        if not m:
            return None
        return m.group(1) or "#" + m.group(2)

    @staticmethod
    def title(lines):
        for l in lines:
            s = re.sub(r"^\s*(#+|title:)\s*", "", l, flags=re.I).strip(" *_")
            if s:
                return s[:160]
        return None

    def requirements(self, lines):
        """Bullets / Given-When-Then under an acceptance-criteria-like heading; otherwise every
        requirement-like bullet or sentence."""
        reqs, in_ac, found_ac, gherkin = [], False, False, []
        for l in lines:
            if AC_HEADING.match(l):
                in_ac = found_ac = True
                rest = HEADING_WORD.sub("", l, count=1).strip()
                if len(rest) > 8:
                    reqs.append(rest)
                continue
            if in_ac and OTHER_HEADING.match(l) and not LIST_ITEM.match(l) and not GHERKIN.match(l):
                in_ac = False
            g = GHERKIN.match(l)
            if g:
                if g.group(1).lower() == "given" and gherkin:     # a new Given starts the next criterion
                    reqs.append(" ".join(gherkin))
                    gherkin = []
                gherkin.append(l.strip())
                continue
            if gherkin:
                reqs.append(" ".join(gherkin))
                gherkin = []
            m = LIST_ITEM.match(l)
            if in_ac and m:
                reqs.append(m.group(1))
            elif in_ac and l.strip() and not found_ac:
                reqs.append(l.strip())
        if gherkin:
            reqs.append(" ".join(gherkin))
        if not reqs:          # no explicit criteria: requirement-like bullets, then sentences
            for l in lines:
                m = LIST_ITEM.match(l)
                if m and REQ_WORDS.search(m.group(1)):
                    reqs.append(m.group(1))
            if not reqs:
                for s in re.split(r"(?<=[.!?])\s+", " ".join(lines[1:] if len(lines) > 1 else lines)):
                    if REQ_WORDS.search(s) and 12 < len(s) < 400:
                        reqs.append(s.strip())
        out, seen = [], set()
        for r in reqs:
            r = re.sub(r"^\[[ xX]\]\s*", "", r).strip()
            if r and r.lower() not in seen:
                seen.add(r.lower())
                out.append({"id": "R%d" % (len(out) + 1), "text": r[:500], "source": "ticket"})
        return out[:40]
