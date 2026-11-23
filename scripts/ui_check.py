#!/usr/bin/env python3
"""Drive the app's UI in a headless browser (Python Playwright) and check what happens.

Usage: ui_check.py --dir <OUT_DIR> --spec <spec.json> [--name ui] [--only T3] [--base-url URL]
                   [--allow-host HOST] [--headed]

The spec format is in qakit/uicheck.py (goto / fill / click / select / expect_text /
expect_request ...). Each scenario records the requests the page sent (form -> API), console
and page errors, and screenshots under OUT_DIR/screens/. Writes OUT_DIR/runs/<name>.json.
Only localhost is allowed; requests to other hosts are aborted.
"""
import argparse
import sys

from qakit import QAError
from qakit.jsonio import load_json, write_json
from qakit.uicheck import UiCheckRunner
from qakit.workspace import Workspace


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--name", default="ui")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--base-url")
    ap.add_argument("--allow-host", action="append", default=[])
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    try:
        ws = Workspace.load(a.dir)
        spec = load_json(a.spec, "spec")
        if a.base_url:
            spec["base_url"] = a.base_url
        res = UiCheckRunner(ws, spec, a.allow_host, a.only, a.headed).run()
    except QAError as e:
        sys.exit("ui_check.py: " + str(e))
    res["spec"] = a.spec
    write_json(ws.path("runs", "%s.json" % a.name), res)
    for r in res["results"]:
        print("%-4s %-7s %s" % (r["id"], r["result"].upper(), r["name"]))
        for s in r["steps"]:
            print("       %s %s%s" % ("✓" if s["ok"] else "✗", s["step"][:100], ("  → " + str(s["detail"])[:160]) if s.get("detail") else ""))
        for q in r["requests"][:12]:
            print("       ⇄ %s %s → %s" % (q["method"], q["url"], q["status"] or q.get("failed")))
        for e in r["console_errors"] + r["page_errors"]:
            print("       console: " + e[:200])
        if r["blocked_external"]:
            print("       blocked %d external request(s), e.g. %s" % (len(r["blocked_external"]), r["blocked_external"][0]))
        print("       screenshots: " + ", ".join(r["screenshots"]))
    print("%d passed, %d failed  RESULT_JSON=runs/%s.json" % (res["passed"], res["failed"], a.name))


if __name__ == "__main__":
    main()
