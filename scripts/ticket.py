#!/usr/bin/env python3
"""Read the ticket the branch implements and list its requirements.

Usage: ticket.py --dir <OUT_DIR> [--file PATH]

Reads <OUT_DIR>/ticket.md (write the user's pasted text there first) or --file, copies it into
OUT_DIR/ticket.md, extracts the ticket id, title and acceptance criteria / requirements, writes
OUT_DIR/ticket.json and prints them. Refine the list in qa.json; this is only a starting point.
"""
import argparse
import os
import shutil
import sys

from qakit import QAError
from qakit.jsonio import write_json
from qakit.ticket import TicketParser
from qakit.workspace import Workspace


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--file", help="ticket file (markdown / text) to copy into OUT_DIR/ticket.md")
    a = ap.parse_args(argv)
    try:
        ws = Workspace.load(a.dir)
        dest = ws.path("ticket.md")
        if a.file:
            src = a.file if os.path.isabs(a.file) else os.path.join(ws.repo, a.file)
            if not os.path.isfile(src):
                raise QAError("ticket file not found: %s" % a.file)
            if os.path.abspath(src) != os.path.abspath(dest):
                shutil.copyfile(src, dest)
        if not os.path.exists(dest):
            raise QAError("no ticket at %s: write the ticket text there, or pass --file" % dest)
        with open(dest, errors="replace") as fh:
            parsed = TicketParser(fh.read()).parse()
    except QAError as e:
        sys.exit("ticket.py: " + str(e))
    write_json(ws.path("ticket.json"), parsed, indent=2)
    title = parsed["title"] or ""
    print("Ticket: %s" % (title if parsed["id"] and parsed["id"] in title else "%s %s" % (parsed["id"] or "(no id)", title)))
    print("Requirements found (%d):" % len(parsed["requirements"]))
    for r in parsed["requirements"]:
        print("  %s  %s" % (r["id"], r["text"]))
    if not parsed["requirements"]:
        print("  none recognised: read the ticket and write the requirements into qa.json yourself")
    print("TICKET_JSON=%s" % ws.path("ticket.json"))


if __name__ == "__main__":
    main()
