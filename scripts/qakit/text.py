"""Text: small, shared text formatting (one-liners, truncation, slugs, line ranges, file URLs).
MarkdownTable: a GitHub-flavoured markdown table with escaped cells."""
import os
import re


class Text(object):
    @staticmethod
    def one_line(text, limit=None):
        """Whitespace collapsed to single spaces, optionally truncated with an ellipsis."""
        s = re.sub(r"\s+", " ", str(text or "")).strip()
        return s if not limit or len(s) <= limit else s[:limit - 1] + "…"

    @staticmethod
    def short(value, n=120):
        """A value as text for digests: None as ∅, truncated with an ellipsis."""
        v = "∅" if value is None else str(value)
        return v if len(v) <= n else v[:n - 1] + "…"

    @staticmethod
    def slugify(text, limit=60):
        s = re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-").lower()
        return (s[:limit].rstrip("-")) or "qa"

    @staticmethod
    def line_ranges(nums):
        """[1, 2, 3, 7, 9, 10] -> '1-3,7,9-10'"""
        out, start, prev = [], None, None
        for n in nums:
            if start is not None and n == prev + 1:
                prev = n
                continue
            if start is not None:
                out.append(str(start) if start == prev else "%d-%d" % (start, prev))
            start = prev = n
        if start is not None:
            out.append(str(start) if start == prev else "%d-%d" % (start, prev))
        return ",".join(out)

    @staticmethod
    def file_url(path):
        return "file://" + os.path.abspath(path).replace(" ", "%20")

    @staticmethod
    def html_escape(text):
        return text.replace("&", "&amp;").replace("<", "&lt;")

    @staticmethod
    def as_list(value):
        return [] if value is None else (value if isinstance(value, list) else [value])


class MarkdownTable(object):
    def __init__(self, head, rows):
        self.head, self.rows = head, rows

    @staticmethod
    def cell(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|")

    def render(self):
        L = ["| " + " | ".join(self.head) + " |", "|" + "|".join("---" for _ in self.head) + "|"]
        L.extend("| " + " | ".join(self.cell(c) for c in r) + " |" for r in self.rows)
        return "\n".join(L)
