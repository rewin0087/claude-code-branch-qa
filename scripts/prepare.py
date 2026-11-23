#!/usr/bin/env python3
"""Start a QA run of the current branch: changes, impact map, how to test, output folder.

Usage: prepare.py [--cwd DIR] [--base BRANCH] [--committed-only] [--path P ...] [--slug NAME]
                  [--ticket "<#123 | ABC-123 | URL | file | first line of the text>"]

Creates <repo>/.branch-qa/<branch>/ (git-ignored) with meta.json, changes.json, impact.json and
tooling.json, and prints a digest: changed areas with their layer, the entry points that reach
them, routes, callers, existing tests, and the suggested test level (e2e_ui / e2e_api /
functional / unit / data / manual). Logic lives in qakit.preparer; this file is only the CLI.
"""
import argparse
import os
import sys

from qakit import QAError
from qakit.preparer import PrepareDigest, PrepareOptions, Preparer


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--base", help="base branch (default: auto-detect main/master/develop/...)")
    ap.add_argument("--committed-only", action="store_true", help="ignore uncommitted and untracked work")
    ap.add_argument("--path", action="append", default=[], help="only QA changes under this path (repeatable)")
    ap.add_argument("--slug", help="output folder name (default: the branch name)")
    ap.add_argument("--ticket", help="ticket reference or the first line of the pasted text (classification only)")
    a = ap.parse_args(argv)
    try:
        meta, impact, tooling = Preparer(PrepareOptions(a.cwd, a.base, a.committed_only, a.ticket, a.slug, a.path)).run()
    except QAError as e:
        sys.exit("prepare.py: " + str(e))
    print(PrepareDigest(meta, impact, tooling).format())


if __name__ == "__main__":
    main()
