"""ResultRows: the scenarios as the results table everyone sees (#, test, type, result, expected?, remarks)."""
from . import vocabulary as V
from .text import Text
from .vocabulary import Outcomes


class ResultRows(object):
    HEAD = ("#", "Test scenario", "Type", "Result", "Expected?", "Remarks")

    def __init__(self, qa):
        self.qa = qa

    def rows(self, remark_limit=None):
        out = []
        for sc in self.qa.get("scenarios") or []:
            out.append((sc.get("id", ""), Text.one_line(sc.get("title")), V.TYPES.get(sc.get("type"), sc.get("type") or ""),
                        V.RESULTS.get(sc.get("result"), sc.get("result") or ""), V.AS_EXPECTED[Outcomes.as_expected(sc)],
                        Text.one_line(sc.get("remarks"), remark_limit)))
        return out

    def counts(self):
        res = [s.get("result") for s in self.qa.get("scenarios") or []]
        return {k: res.count(k) for k in V.RESULTS if res.count(k)}

    def counts_text(self):
        c = self.counts()
        total = sum(c.values())
        return "%d scenario%s: %s" % (total, "" if total == 1 else "s",
                                      ", ".join("%d %s" % (n, k.replace("_", " ")) for k, n in c.items()) or "none")
