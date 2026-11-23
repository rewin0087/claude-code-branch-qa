"""CallerFinder: who calls the changed symbols (app code and tests), and the entry points that reach them."""
import re

from .diffparse import SymbolName
from .layers import ENTRY_LAYERS, IMPORT_LINE, LayerClassifier


class CallerFinder(object):
    def __init__(self, git, max_hits=40):
        self.git, self.max_hits = git, max_hits
        self._cache = {}

    def callers(self, symbol, defined_in):
        """{"app": [(path, line, text)], "tests": [...]} of lines that mention the symbol elsewhere."""
        if symbol in self._cache:
            return self._cache[symbol]
        out = {"app": [], "tests": []}
        if len(symbol) < 4 or symbol in ("call", "perform", "create", "update", "index", "show", "save", "run", "execute",
                                         "initialize", "__init__", "handle", "process", "render", "destroy", "new", "edit"):
            self._cache[symbol] = out
            return out
        defs = re.compile(r"^\s*(def|class|module|function|func|fn|const|let|var|export\s+(default\s+)?(function|class|const))\s")
        for path, line, text in self.git.grep_word(symbol, limit=600):
            if path == defined_in or re.search(r"(^|/)(\.branch-qa|\.investigate|\.branch-review|vendor|node_modules|dist|build)/", path):
                continue
            if defs.match(text) or IMPORT_LINE.match(text) or LayerClassifier.layer(path) in ("docs", "config"):
                continue
            bucket = "tests" if LayerClassifier.layer(path) == "test" else "app"
            if len(out[bucket]) < self.max_hits:
                out[bucket].append((path, line, text.strip()[:160]))
        call = re.compile(r"[.\s(]%s\s*\(|^%s\s*\(|%s\b" % ((re.escape(symbol),) * 2 + (r"\b(?:except|rescue|catch|raise|throw|new)\b.*\b" + re.escape(symbol),)))
        for k in out:      # real calls / raises first, mentions (strings, comments) last
            out[k].sort(key=lambda h: 0 if call.search(h[2]) else 1)
        self._cache[symbol] = out
        return out

    def entry_points(self, symbols, defined_in, sources, depth=2):
        """Entry files (routes, controllers, UI, jobs, callbacks) that reach the symbols within `depth` hops."""
        found, frontier, seen = [], [(s, defined_in) for s in symbols], set()
        for _ in range(depth):
            nxt = []
            for sym, src in frontier:
                for path, line, text in self.callers(sym, src)["app"]:
                    if (path, sym) in seen:
                        continue
                    seen.add((path, sym))
                    layer = LayerClassifier.refine(path, LayerClassifier.layer(path), sources.get(path).lines)
                    if layer in ENTRY_LAYERS:
                        found.append({"file": path, "line": line, "layer": layer, "via": sym, "text": text})
                    else:
                        enclosing = sources.get(path).enclosing_definition(line)
                        if enclosing:
                            name = SymbolName.of(enclosing["text"])
                            if name:
                                nxt.append((name, path))
            frontier = nxt[:20]
        by_file = {}
        for e in found:          # one entry per file: its first (best) line, and every symbol that leads there
            cur = by_file.get(e["file"])
            if cur is None:
                by_file[e["file"]] = dict(e, via=[e["via"]])
            elif e["via"] not in cur["via"]:
                cur["via"].append(e["via"])
        return [dict(e, via=", ".join(e["via"])) for e in by_file.values()][:15]
