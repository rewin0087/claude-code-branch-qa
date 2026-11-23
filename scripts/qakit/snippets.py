"""SnippetCollector: embed the source code the QA run points at, so the report is self-contained."""
import os

from .sourcefile import SourceCache

MAX_FULL_LINES = 1500     # embed the whole file up to this size
WINDOW = 40               # otherwise: this many lines around every referenced line
MAX_FILES = 60


class SnippetCollector(object):
    def __init__(self, repo):
        self.sources = SourceCache(repo)
        self.refs = {}

    def add(self, f, *lines):
        if f and not os.path.isabs(f):
            self.refs.setdefault(f, set()).update(l for l in lines if isinstance(l, int))

    def add_qa(self, qa, impact=None):
        """Every anchor: areas, scenario steps, code paths, failures, fixes, findings, changed lines."""
        for a in qa.get("areas") or []:
            for f in a.get("files") or []:
                self.add(f)
            if a.get("entry"):
                self.add(a["entry"].get("file"), a["entry"].get("line"))
        for sc in qa.get("scenarios") or []:
            for st in (sc.get("steps") or []) + (sc.get("code_path") or []):
                self.add(st.get("file"), st.get("line"), st.get("end_line"))
            for k in ("failure", "fix"):
                if sc.get(k):
                    self.add(sc[k].get("file"), sc[k].get("line"), sc[k].get("end_line"))
        for f in qa.get("findings") or []:
            self.add(f.get("file"), f.get("line"), f.get("end_line"))
        for a in (impact or {}).get("areas") or []:
            if a.get("layer") not in ("docs", "test") and a.get("added_ranges"):
                self.add(a["path"], *[n for r in a["added_ranges"][:20] for n in r])
        return self

    def build(self):
        """{file: {"start": first line no, "lines": [...], "total": n}}"""
        out = {}
        for rel, lns in sorted(self.refs.items(), key=lambda kv: -len(kv[1]))[:MAX_FILES]:
            lines = self.sources.get(rel).lines
            if lines is None:
                continue
            if len(lines) <= MAX_FULL_LINES or not lns:
                out[rel] = {"start": 1, "lines": lines[:MAX_FULL_LINES], "total": len(lines)}
                continue
            lo = max(1, min(lns) - WINDOW)
            hi = min(len(lines), max(lns) + WINDOW, lo + MAX_FULL_LINES)   # widely spread anchors: first window only
            out[rel] = {"start": lo, "lines": lines[lo - 1:hi], "total": len(lines)}
        return out
