#!/usr/bin/env python3
"""Round-trip test for update-applications.py: writing then re-reading the
tracker must not lose fields. Catches the 'applied'/'date' label mismatch.

Run:  python3 test/test_update_applications.py
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "update-applications.py")


def run(records, tracker):
    subprocess.run(
        [sys.executable, SCRIPT, "--tracker", tracker, "--no-ledger-sync"],
        input=json.dumps(records), capture_output=True, text=True, check=True,
    )


def main():
    failures = []

    def check(name, cond, detail=""):
        print(("  ok: " if cond else "  FAIL: ") + name + ("" if cond else f" {detail}"))
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        tracker = os.path.join(tmp, "applications.md")
        recs = [
            {"company": "CASABOT", "title": "Head of Product Design", "status": "interviewing",
             "date": "2026-06-02", "location": "Dubai", "work_mode": "onsite",
             "source": "LinkedIn", "note": "two interviews"},
            {"company": "Etihad", "title": "Design Experience Manager", "status": "acknowledged",
             "date": "2026-06-02", "location": "Abu Dhabi", "work_mode": "onsite"},
        ]
        run(recs, tracker)
        first = open(tracker).read()
        check("date rendered as 'applied'", "- applied: 2026-06-02" in first)
        check("location + work mode combined", "- location: Dubai (onsite)" in first)
        check("interviewing section present", "## Interviewing" in first)

        # Re-run with NO new records: nothing may be lost (the round-trip bug).
        run([], tracker)
        second = open(tracker).read()
        check("date survives a no-op re-run", "- applied: 2026-06-02" in second)
        check("location survives a no-op re-run", "- location: Dubai (onsite)" in second)
        check("note survives a no-op re-run", "two interviews" in second)

        # A later lifecycle stage overrides; an earlier one does not.
        run([{"company": "CASABOT", "title": "Head of Product Design", "status": "rejected", "date": "2026-06-20"}], tracker)
        third = open(tracker).read()
        check("rejection moves role to Closed", "## Closed" in third and "rejected" in third)
        run([{"company": "CASABOT", "title": "Head of Product Design", "status": "applied"}], tracker)
        fourth = open(tracker).read()
        check("earlier stage does not downgrade a closed role", "rejected" in fourth)

    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed")


if __name__ == "__main__":
    main()
