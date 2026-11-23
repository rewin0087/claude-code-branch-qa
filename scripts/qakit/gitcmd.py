"""Git: a thin, testable wrapper around the git CLI for one repository."""
import os
import re
import subprocess

from .errors import QAError

BASE_CANDIDATES = ("main", "master", "develop", "development", "dev", "trunk")


class Git(object):
    def __init__(self, cwd):
        self.cwd = cwd

    def run(self, args, check=True):
        """stdout of `git <args>`. With check=False a failing command returns ""."""
        r = subprocess.run(["git", "-c", "core.quotepath=off"] + list(args), cwd=self.cwd,
                           capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            if check:
                raise QAError("git %s failed:\n%s" % (" ".join(args), r.stderr.strip()))
            return ""
        return r.stdout

    # ---- facts ---------------------------------------------------------------------------
    def root(self):
        return self.run(["rev-parse", "--show-toplevel"], check=False).strip()

    def branch(self):
        return self.run(["rev-parse", "--abbrev-ref", "HEAD"], check=False).strip()

    def head_sha(self):
        return self.run(["rev-parse", "--short", "HEAD"], check=False).strip()

    def ref_exists(self, ref):
        return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"], cwd=self.cwd,
                              capture_output=True).returncode == 0

    def resolve_ref(self, ref):
        """ref, or origin/<ref> when only the remote-tracking branch exists, else None."""
        for cand in (ref, "origin/" + ref):
            if self.ref_exists(cand):
                return cand
        return None

    def remote_web_url(self):
        """git@github.com:me/repo.git | https://gitlab.com/g/repo.git -> https://host/path"""
        remote = self.run(["config", "--get", "remote.origin.url"], check=False).strip()
        m = re.match(r"^(?:git@|ssh://git@)([^:/]+)[:/](.+?)(?:\.git)?/?$", remote) or \
            re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote)
        return "https://%s/%s" % (m.group(1), m.group(2)) if m else None

    def ls_files(self):
        """Tracked plus untracked-but-not-ignored files, relative to the repo root."""
        out = self.run(["ls-files", "--cached", "--others", "--exclude-standard"], check=False)
        return [p for p in out.split("\n") if p]

    def grep_word(self, word, limit=400):
        """[(path, line, text)] for lines containing the literal word."""
        out = []
        for row in self.run(["grep", "-n", "-I", "-w", "-F", word], check=False).split("\n"):
            parts = row.split(":", 2)
            if len(parts) == 3 and parts[1].isdigit():
                out.append((parts[0], int(parts[1]), parts[2]))
                if len(out) >= limit:
                    break
        return out

    # ---- the branch under QA -------------------------------------------------------------
    def detect_base(self, current, head="HEAD"):
        """The candidate base whose merge-base is closest to head (fewest commits ahead)."""
        cands = []
        origin_head = self.run(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], check=False).strip()
        if origin_head:
            cands.append(origin_head.replace("refs/remotes/", ""))
        for name in BASE_CANDIDATES:
            cands += [name, "origin/" + name]
        best, seen = None, set()
        for ref in cands:
            if ref in seen or ref in (current, "origin/" + current) or not self.ref_exists(ref):
                continue
            seen.add(ref)
            mb = self.run(["merge-base", ref, head], check=False).strip()
            if not mb:
                continue
            ahead = int(self.run(["rev-list", "--count", mb + ".." + head]).strip() or 0)
            if best is None or ahead < best[1]:
                best = (ref, ahead)
        return best[0] if best else None

    def merge_base(self, base, head="HEAD"):
        return self.run(["merge-base", base, head]).strip()

    def commits(self, since, head="HEAD"):
        raw = self.run(["log", "--no-merges", "--format=%h%x1f%an%x1f%ad%x1f%s", "--date=short", since + ".." + head],
                       check=False)
        return [dict(zip(("short", "author", "date", "subject"), l.split("\x1f"))) for l in raw.strip().split("\n") if l]

    def diff(self, since, uncommitted=True, context=3):
        """Unified diff of the branch: merge-base -> working tree (uncommitted work included) or HEAD."""
        args = ["diff", "--no-color", "--no-ext-diff", "-M", "-U%d" % context, since]
        if not uncommitted:
            args.append("HEAD")
        return self.run(args)

    def untracked(self):
        out = self.run(["ls-files", "--others", "--exclude-standard"], check=False)
        return [p for p in out.split("\n") if p]

    def ensure_ignored(self, entry=".branch-qa/"):
        """Keep QA output out of commits without touching the tracked .gitignore."""
        git_dir = self.run(["rev-parse", "--git-common-dir"], check=False).strip()
        if not git_dir:
            return
        exclude = os.path.join(git_dir if os.path.isabs(git_dir) else os.path.join(self.cwd, git_dir), "info", "exclude")
        try:
            os.makedirs(os.path.dirname(exclude), exist_ok=True)
            existing = open(exclude).read() if os.path.exists(exclude) else ""
            if entry not in existing.split("\n"):
                with open(exclude, "a") as fh:
                    fh.write(("" if existing.endswith("\n") or not existing else "\n") + entry + "\n")
        except OSError:
            pass
