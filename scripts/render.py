#!/usr/bin/env python3
"""Validate qa.json and build the interactive HTML report + chat summary.

Usage: render.py --dir <OUT_DIR> [--no-open] [--out report.html]

Embeds the referenced source code, test runs, HTTP/UI results and recorded traces, writes
report.html, summary.md and the ticket comment, and prints the summary for the chat. Warnings
are printed as ACTION REQUIRED: fix them in qa.json and run again.
Logic lives in qakit.renderer (Renderer, RenderResult) and qakit.report; this file is only the CLI.
"""
import argparse
import sys

from qakit import QAError
from qakit.renderer import Renderer
from qakit.report import ReportOpener


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="OUT_DIR printed by prepare.py")
    ap.add_argument("--out", help="output HTML path (default <dir>/report.html)")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)
    try:
        renderer = Renderer(a.dir)
        result = renderer.render(a.out)
    except QAError as e:
        sys.exit("render.py: " + str(e))
    for note in renderer.notes:
        print("WARNING: " + note)
    print(result.format())
    if result.errors:
        sys.exit(1)
    if not a.no_open:
        problem = ReportOpener.open(result.report_path)
        if problem:
            print(problem)


if __name__ == "__main__":
    main()
