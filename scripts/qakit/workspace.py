"""Workspace: the repository under QA and its output folder (<repo>/.branch-qa/<branch-slug>/)."""
import os
import time

from .errors import QAError
from .gitcmd import Git
from .jsonio import JsonFile

WALK_SKIP = {".git", "node_modules", "vendor", ".venv", "venv", "dist", "build", "tmp", "coverage", ".branch-qa", ".investigate",
             ".branch-review", "__pycache__", ".tox", ".next", "target"}
SUBDIRS = ("tests", "logs", "trace", "runs", "screens", "data")


class Workspace(object):
    def __init__(self, repo, out_dir=None, meta=None):
        self.repo = repo
        self.git = Git(repo)
        self.out_dir = out_dir
        self.meta = meta or {}
        self._files = None

    @classmethod
    def for_path(cls, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            raise QAError("not a directory: %s" % path)
        root = Git(path).root()
        if not root:
            raise QAError("%s is not inside a git repository: /branch-qa checks the changes of the current branch." % path)
        return cls(root)

    @classmethod
    def load(cls, out_dir):
        p = os.path.join(out_dir, "meta.json")
        if not os.path.exists(p):
            raise QAError("meta.json not found in %s (run prepare.py first)" % out_dir)
        meta = JsonFile.load(p, "meta.json")
        return cls(meta["repo"], os.path.abspath(out_dir), meta)

    @property
    def files(self):
        if self._files is None:
            self._files = self.git.ls_files() or self._walk()
        return self._files

    def _walk(self):
        out = []
        for d, dirs, names in os.walk(self.repo):
            dirs[:] = [x for x in dirs if x not in WALK_SKIP and not x.startswith(".")]
            out.extend(os.path.relpath(os.path.join(d, n), self.repo) for n in names)
            if len(out) > 50000:
                break
        return out

    def create(self, slug):
        """Create (or reuse) .branch-qa/<slug>/ and keep it out of git."""
        self.out_dir = os.path.join(self.repo, ".branch-qa", slug)
        for sub in ("",) + SUBDIRS:
            os.makedirs(os.path.join(self.out_dir, sub), exist_ok=True)
        self.git.ensure_ignored()
        return self.out_dir

    def write_meta(self, data):
        self.meta = dict({"repo": self.repo, "repo_name": os.path.basename(self.repo), "out_dir": self.out_dir,
                          "created": time.strftime("%Y-%m-%d %H:%M:%S")}, **data)
        JsonFile.write(self.path("meta.json"), self.meta, indent=2)
        return self.meta

    def update_meta(self, **kw):
        self.meta.update(kw)
        JsonFile.write(self.path("meta.json"), self.meta, indent=2)

    def path(self, *parts):
        return os.path.join(self.out_dir, *parts)

    def read_text(self, rel):
        try:
            with open(os.path.join(self.repo, rel), errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    def optional_json(self, name, on_error=None):
        p = self.path(name)
        if not os.path.exists(p):
            return None
        try:
            return JsonFile.load(p, name)
        except QAError as e:
            if on_error:
                on_error("ignoring " + str(e))
            return None
