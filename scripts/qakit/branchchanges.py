"""BranchChanges: the branch under QA -> its base, merge-base and changed files.

Changed files come from `git diff <merge-base>` (uncommitted work included unless committed-only)
plus untracked files, minus lockfiles, generated assets and the skills' own output folders.
"""
import re

from .diffparse import ChangedFile, DiffParser
from .errors import QAError

SKIP_FILES = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Gemfile\.lock|poetry\.lock|Pipfile\.lock|composer\.lock|"
                        r"go\.sum|Cargo\.lock)$|\.(min\.js|map|snap|svg|png|jpe?g|gif|ico|pdf|woff2?)$|(^|/)(\.branch-qa|\.investigate|\.branch-review)/")
MAX_UNTRACKED_LINES = 4000


class BranchChanges(object):
    def __init__(self, workspace, base=None, committed_only=False, paths=()):
        self.ws, self.git = workspace, workspace.git
        self.base_option, self.committed_only, self.paths = base, committed_only, list(paths)

    def base(self, branch):
        """-> (base ref or None, the commit to diff from). On the base branch itself: (None, HEAD)."""
        if self.base_option:
            base = self.git.resolve_ref(self.base_option)
            if not base:
                raise QAError("Base branch '%s' not found." % self.base_option)
        else:
            base = self.git.detect_base(branch)
        if not base:      # on the base branch itself (or no base): QA the uncommitted work against HEAD
            return None, "HEAD" if self.git.run(["rev-parse", "--verify", "--quiet", "HEAD"], check=False) else None
        return base, self.git.merge_base(base)

    def files(self, since):
        files = []
        if since:
            files = DiffParser().parse(self.git.diff(since, uncommitted=not self.committed_only))
        if not self.committed_only:
            known = {f.path for f in files}
            for rel in self.git.untracked():
                if rel not in known and not SKIP_FILES.search(rel):
                    files.append(self._untracked(rel))
        files = [f for f in files if f and not SKIP_FILES.search(f.path)]
        if self.paths:
            files = [f for f in files if any(f.path == p or f.path.startswith(p.rstrip("/") + "/") for p in self.paths)]
        return files

    def source_lines(self, rel):
        text = self.ws.read_text(rel)
        return text.split("\n") if text is not None else None

    def _untracked(self, rel):
        text = self.ws.read_text(rel)
        if text is None or "\0" in text[:4000]:
            return None
        cf = ChangedFile(rel, status="added")
        lines = text.split("\n")[:MAX_UNTRACKED_LINES]
        cf.added = list(range(1, len(lines) + 1))
        cf.added_text = lines
        return cf
