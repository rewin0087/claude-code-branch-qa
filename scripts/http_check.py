#!/usr/bin/env python3
"""Send HTTP scenarios to the app running on localhost and check the responses.

Usage: http_check.py --dir <OUT_DIR> --spec <spec.json> [--name http] [--only T1 --only T2]
                     [--base-url http://localhost:3000] [--allow-host HOST]

The spec format is in qakit/httpcheck.py (requests with json/form bodies, expectations with
matchers, values saved from one response and reused as {{name}}, cookies kept across requests).
Writes OUT_DIR/runs/<name>.json and prints one line per request with the failed assertions.
Only loopback hosts are allowed unless --allow-host names a local/disposable environment.
"""
import argparse
import sys

from qakit import QAError
from qakit.httpcheck import HttpCheckRunner
from qakit.jsonio import load_json, write_json
from qakit.workspace import Workspace


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--name", default="http", help="result file name under runs/ (default http)")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--base-url")
    ap.add_argument("--allow-host", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        ws = Workspace.load(a.dir)
        spec = load_json(a.spec, "spec")
        if a.base_url:
            spec["base_url"] = a.base_url
        res = HttpCheckRunner(spec, a.allow_host, a.only).run()
    except QAError as e:
        sys.exit("http_check.py: " + str(e))
    res["spec"] = a.spec
    write_json(ws.path("runs", "%s.json" % a.name), res)
    for r in res["results"]:
        resp = r.get("response") or {}
        req = r.get("request") or {}
        print("%-4s %-7s %s %s → %s (%s ms)  %s" % (r["id"], r["result"].upper(), req.get("method", ""), req.get("url", ""),
                                                 resp.get("status", "-"), resp.get("ms", "-"), r.get("name", "")))
        if r.get("error"):
            print("       error: " + r["error"])
        for x in r["assertions"]:
            if not x["ok"]:
                print("       ✗ %s: expected %s, got %s" % (x["check"], x["expected"], str(x["actual"])[:200]))
    print("%d passed, %d failed  RESULT_JSON=runs/%s.json" % (res["passed"], res["failed"], a.name))


if __name__ == "__main__":
    main()
