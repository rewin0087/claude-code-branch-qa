#!/usr/bin/env python3
"""Read the ticket the branch implements and list its requirements.

Usage: ticket.py --dir <OUT_DIR> [--file PATH]

Reads <OUT_DIR>/ticket.md (write the user's pasted text there first) or --file, copies it into
OUT_DIR/ticket.md, extracts the ticket id, title and acceptance criteria / requirements, writes
OUT_DIR/ticket.json and prints them. Refine the list in qa.json; this is only a starting point.
Logic lives in qakit.ticket (TicketFile, TicketParser); this file is only the CLI.
"""
import argparse
import sys

from qakit import QAError
from qakit.ticket import TicketDigest, TicketFile
from qakit.workspace import Workspace


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--file", help="ticket file (markdown / text) to copy into OUT_DIR/ticket.md")
    a = ap.parse_args(argv)
    try:
        ws = Workspace.load(a.dir)
        ticket = TicketFile(ws)
        if a.file:
            ticket.import_file(a.file)
        parsed = ticket.parse()
    except QAError as e:
        sys.exit("ticket.py: " + str(e))
    print(TicketDigest(parsed, ws.path("ticket.json")).format())


if __name__ == "__main__":
    main()
