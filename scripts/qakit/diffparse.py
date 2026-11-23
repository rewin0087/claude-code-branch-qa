"""DiffParser: `git diff` -> changed files with their added/removed line numbers and touched symbols."""
import re

from .sourcefile import DEFINITION_LINE

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
DIFF_GIT_RE = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$')
NAME_RX = re.compile(
    r"(?:def|function|func|fun|fn|class|module|interface|struct|enum|trait|type)\s+(?:\([^)]*\)\s*)?"
    r"(?:self\.)?([A-Za-z_$][\w$]*[!?]?)"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
    r"|^\s*(?:(?:public|private|protected|static|async|override|final|internal)\s+)+[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\(")


class SymbolName(object):
    @staticmethod
    def of(text):
        """The name a definition line defines: `def refund(` -> refund, `class Order` -> Order."""
        m = NAME_RX.search(text or "")
        if not m:
            return None
        return next(g for g in m.groups() if g)


class ChangedFile(object):
    def __init__(self, path, old_path=None, status="modified"):
        self.path, self.old_path, self.status = path, old_path, status
        self.added, self.removed = [], []        # new-file line numbers / old-file line numbers
        self.added_text, self.removed_text = [], []
        self.hunk_contexts = []                  # the function/class names git prints after @@
        self.binary = False

    @property
    def additions(self):
        return len(self.added)

    @property
    def deletions(self):
        return len(self.removed)

    def symbols(self, source_lines=None):
        """Names of the definitions the change touches: hunk headers, changed definition lines,
        and (when the new source is given) the definition enclosing each added line."""
        names = []

        def add(n):
            if n and n not in names and len(n) > 1:
                names.append(n)
        for ctx in self.hunk_contexts:
            add(SymbolName.of(ctx))
        for text in self.added_text + self.removed_text:
            if DEFINITION_LINE.match(text):
                add(SymbolName.of(text))
        if source_lines:
            for n in self.added:
                for i in range(min(n, len(source_lines)) - 1, -1, -1):
                    if DEFINITION_LINE.match(source_lines[i]):
                        add(SymbolName.of(source_lines[i]))
                        break
        return names

    def ranges(self):
        """Added lines as [start, end] spans."""
        out = []
        for n in self.added:
            if out and n == out[-1][1] + 1:
                out[-1][1] = n
            else:
                out.append([n, n])
        return out

    def to_dict(self, source_lines=None):
        return {"path": self.path, "old_path": self.old_path if self.old_path != self.path else None,
                "status": self.status, "binary": self.binary, "additions": self.additions,
                "deletions": self.deletions, "added_ranges": self.ranges(), "symbols": self.symbols(source_lines)}


class DiffParser(object):
    def parse(self, text):
        files, cur, old_n, new_n = [], None, 0, 0
        for raw in text.split("\n"):
            if raw.startswith("diff --git "):
                m = DIFF_GIT_RE.match(raw)
                cur = ChangedFile(m.group(2) if m else raw.split(" b/")[-1], m.group(1) if m else None)
                files.append(cur)
                continue
            if cur is None:
                continue
            if raw.startswith("new file mode"):
                cur.status = "added"
            elif raw.startswith("deleted file mode"):
                cur.status = "deleted"
            elif raw.startswith("rename from "):
                cur.status, cur.old_path = "renamed", raw[len("rename from "):]
            elif raw.startswith("rename to "):
                cur.path = raw[len("rename to "):]
            elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
                cur.binary = True
            elif raw.startswith("@@"):
                m = HUNK_RE.match(raw)
                if m:
                    old_n, new_n = int(m.group(1)), int(m.group(3))
                    if m.group(5).strip():
                        cur.hunk_contexts.append(m.group(5).strip())
            elif raw.startswith("+++") or raw.startswith("---") or raw.startswith("index "):
                continue
            elif raw.startswith("+"):
                cur.added.append(new_n)
                cur.added_text.append(raw[1:])
                new_n += 1
            elif raw.startswith("-"):
                cur.removed.append(old_n)
                cur.removed_text.append(raw[1:])
                old_n += 1
            elif raw.startswith(" "):
                old_n += 1
                new_n += 1
        return files
