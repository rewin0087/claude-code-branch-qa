#!/usr/bin/env python3
"""Send HTTP scenarios to the app running on localhost and check the responses.

Usage: http_check.py --dir <OUT_DIR> --spec <spec.json> [--name http] [--only T1 --only T2]
                     [--base-url http://localhost:3000] [--allow-host HOST]

The spec format is in qakit/httpcheck.py (requests with json/form bodies, expectations with
matchers, values saved from one response and reused as {{name}}, cookies kept across requests).
Writes OUT_DIR/runs/<name>.json and prints one line per request with the failed assertions.
Only loopback hosts are allowed unless --allow-host names a local/disposable environment.
Logic lives in qakit.httpcheck; this file is only the CLI.
"""
import argparse
import sys

from qakit import QAError
from qakit.httpcheck import HttpCheckDigest, HttpCheckRunner
from qakit.jsonio import JsonFile
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
        spec = JsonFile.load(a.spec, "spec")
        if a.base_url:
            spec["base_url"] = a.base_url
        res = HttpCheckRunner(spec, a.allow_host, a.only).run()
    except QAError as e:
        sys.exit("http_check.py: " + str(e))
    res["spec"] = a.spec
    JsonFile.write(ws.path("runs", "%s.json" % a.name), res)
    print(HttpCheckDigest(res, a.name).format())


if __name__ == "__main__":
    main()
