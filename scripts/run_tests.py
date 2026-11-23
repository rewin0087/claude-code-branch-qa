#!/usr/bin/env python3
"""Run a test command (the project's runner) for one or more scenarios and record the result.

Usage: run_tests.py --dir <OUT_DIR> --id T1 [--env KEY=VAL ...] [--junit PATH] [--timeout 900]
                    [--cwd DIR] -- <command ...>

Saves the full output to OUT_DIR/logs/<id>.txt and the result to OUT_DIR/runs/<id>.json (exit
code, runner summary lines, failing test names, JUnit cases when --junit is given). Refuses
production environments and non-local DATABASE_URLs. Prints a short digest.
Logic lives in qakit.testrun; this file is only the CLI.
"""
import argparse
import sys

from qakit import QAError
from qakit.testrun import TestRun, TestRunDigest
from qakit.workspace import Workspace


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--id", required=True, help="scenario id(s) this run covers, e.g. T1 or T1-T4")
    ap.add_argument("--env", action="append", default=[], help="KEY=VALUE for the command (repeatable)")
    ap.add_argument("--junit", help="JUnit XML the command writes, to read per-test results from")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--cwd", help="where to run (default: the repo root)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        sys.exit("run_tests.py: give the command after --")
    try:
        env = dict(kv.split("=", 1) for kv in a.env)
        r = TestRun(Workspace.load(a.dir), a.id, cmd, env, a.cwd, a.timeout, a.junit).run()
    except ValueError:
        sys.exit("run_tests.py: --env takes KEY=VALUE")
    except QAError as e:
        sys.exit("run_tests.py: " + str(e))
    print(TestRunDigest(r).format())


if __name__ == "__main__":
    main()
