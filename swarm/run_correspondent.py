"""Draft this week's Correspondent issue. Independent of the daily swarm.

Reads stored digests. Calls no external source. Never publishes.
"""

from __future__ import annotations

import argparse
import logging
import sys

from swarm.agents.correspondent import write_issue
from swarm.db import init_db
from swarm.lock import LockBusy, acquire_lock, release_lock
from swarm.publish_gate import PUBLISH_PATHS

log = logging.getLogger("correspondent")

# Do not add --publish. The empty tuple is the mechanism, not a comment.
assert PUBLISH_PATHS == ()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft the weekly Correspondent issue")
    parser.add_argument("--force", action="store_true", help="Ignore an existing lock")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db()
    if not args.force:
        try:
            acquire_lock(0, name="correspondent")
        except LockBusy as exc:
            print(str(exc), file=sys.stderr)
            return 2
    try:
        row = write_issue()
    finally:
        release_lock("correspondent")
    if row is None:
        print("no curated question in the last 7 days", file=sys.stderr)
        return 1
    print(
        f"ISSUE_DRAFT_OK {row.week_ending} rule={row.selection_rule} "
        f"words={row.word_count} gate={row.publish_gate_open} "
        f"voice={row.voice_ready} status={row.status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
