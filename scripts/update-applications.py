#!/usr/bin/env python3
"""Merge application-lifecycle records into the vault tracker and sync the ledger.

Usage:
    cat records.json | python3 update-applications.py
    cat records.json | python3 update-applications.py --tracker ~/cairn/career/applications.md

records.json: a list of application records extracted from Gmail (by the agent,
which reads the fuzzy email text). Each record:
    {"company": "Etihad Airways", "title": "Design Experience Manager",
     "status": "acknowledged", "date": "2026-06-02",
     "location": "Abu Dhabi", "source": "company site", "note": "..."}

This script is the deterministic half: it does NOT read Gmail. It merges
records into the human-readable tracker (preserving hand-entered roles and
never downgrading a later lifecycle stage), regroups by status, and syncs
matched roles in the pipeline ledger.

Status lifecycle (later stages never overwritten by earlier ones):
    applied < acknowledged < interviewing < {rejected, offer, withdrawn}

Ledger sync: a record updates a ledger row ONLY when company AND title both
fuzzy-match (same rules as deduplicate-jobs.py). A company-only match never
touches the ledger, because the role applied to may differ from the role the
pipeline surfaced (observed: GovTech rejection was for a different title).
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TRACKER = os.path.expanduser("~/cairn/career/applications.md")
DEFAULT_LEDGER = os.path.join(ROOT, "data", "ledger.db")

STAGE_ORDER = {"applied": 1, "acknowledged": 2, "interviewing": 3,
               "rejected": 4, "offer": 4, "withdrawn": 4}
SECTIONS = [("Awaiting response", {"applied", "acknowledged"}),
            ("Interviewing", {"interviewing"}),
            ("Closed", {"rejected", "offer", "withdrawn"})]

INTRO = (
    "Tracks roles you have actually applied to and their outcomes, drawn from "
    "Gmail (acknowledgements, rejections, interview invitations) plus anything "
    "you add by hand. Independent of the screen-alerts pipeline: it follows "
    "what you applied to, however you found it.\n\n"
    "Status values: applied, acknowledged, interviewing, rejected, offer, withdrawn."
)


def norm_company(name):
    name = (name or "").lower().strip()
    for s in [" inc", " inc.", " llc", " ltd", " ltd.", " gmbh", " pty", " co.", " corp", " corporation", " limited"]:
        if name.endswith(s):
            name = name[:-len(s)]
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", name)).strip()


def norm_title(title):
    title = (title or "").lower().strip()
    title = re.sub(r"\([^)]*\)", "", title)
    title = re.sub(r"\b(remote|hybrid|onsite|full.?time|part.?time|contract)\b", "", title)
    return re.sub(r"\s+", " ", title).strip()


def fuzzy(a, b, thresh):
    return bool(a) and bool(b) and SequenceMatcher(None, a, b).ratio() >= thresh


def rec_key(r):
    return (norm_company(r.get("company", "")), norm_title(r.get("title", "")))


def parse_tracker(path):
    """Parse existing tracker into records keyed by (norm_company, norm_title)."""
    records = {}
    if not os.path.exists(path):
        return records
    current = None
    for line in open(path, encoding="utf-8"):
        h = re.match(r"^###\s+(.*?):\s+(.*)$", line.strip())
        if h:
            current = {"title": h.group(1).strip(), "company": h.group(2).strip()}
            records[rec_key(current)] = current
            continue
        f = re.match(r"^-\s+(\w[\w ]*?):\s+(.*)$", line.strip())
        if f and current is not None:
            key, val = f.group(1).strip(), f.group(2).strip()
            if key == "applied":   # rendered label for the internal "date" field
                key = "date"
            current[key] = val
    return records


def merge(existing, incoming):
    """Merge incoming records into existing, honoring lifecycle order."""
    for r in incoming:
        k = rec_key(r)
        if k in existing:
            cur = existing[k]
            cur_stage = STAGE_ORDER.get(cur.get("status", "applied"), 1)
            new_stage = STAGE_ORDER.get(r.get("status", "applied"), 1)
            if new_stage >= cur_stage:
                cur["status"] = r.get("status", cur.get("status"))
                for fld in ("date", "location", "work_mode", "source", "note"):
                    if r.get(fld):
                        cur[fld] = r[fld]
        else:
            existing[k] = dict(r)
    return existing


def render(records, path):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = ["---", "type: application-tracker", f"updated: {today}", "---", "",
           "# Job applications", "", INTRO, ""]
    recs = list(records.values())
    for heading, statuses in SECTIONS:
        group = [r for r in recs if r.get("status") in statuses]
        if not group:
            continue
        out.append(f"## {heading}")
        out.append("")
        for r in sorted(group, key=lambda x: x.get("date", ""), reverse=True):
            out.append(f"### {r.get('title','(unknown)')}: {r.get('company','(unknown)')}")
            if r.get("status"):
                out.append(f"- status: {r['status']}")
            if r.get("date"):
                out.append(f"- applied: {r['date']}")
            # Location and work mode shown together: "Dubai (onsite)", "Remote",
            # or "Remote, US". Whichever fields we have.
            loc, wm = r.get("location", ""), r.get("work_mode", "")
            if loc and wm and wm.lower() not in loc.lower():
                out.append(f"- location: {loc} ({wm})")
            elif loc:
                out.append(f"- location: {loc}")
            elif wm:
                out.append(f"- location: {wm}")
            for fld in ("source", "note"):
                if r.get(fld):
                    out.append(f"- {fld}: {r[fld]}")
            out.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")


def sync_ledger(incoming, db_path):
    """Update ledger rows for records that match company AND title."""
    if not os.path.exists(db_path):
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT key, company, title, status FROM jobs").fetchall()
    updated = 0
    outcome_to_status = {"rejected": "rejected", "offer": "offer",
                         "acknowledged": "applied", "applied": "applied",
                         "interviewing": "applied", "withdrawn": "withdrawn"}
    for r in incoming:
        rc, rt = norm_company(r.get("company", "")), norm_title(r.get("title", ""))
        target = outcome_to_status.get(r.get("status", ""))
        if not target:
            continue
        for row in rows:
            if fuzzy(rc, norm_company(row["company"]), 0.85) and fuzzy(rt, norm_title(row["title"]), 0.8):
                if row["status"] in ("applied", "rejected", "offer", "withdrawn") and target == "applied":
                    break  # don't downgrade a known outcome to plain applied
                conn.execute("UPDATE jobs SET status=?, status_updated=? WHERE key=?",
                             (target, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), row["key"]))
                updated += 1
                print(f"  ledger: {row['company']} / {row['title'][:40]} -> {target}", file=sys.stderr)
                break
    conn.commit()
    conn.close()
    return updated


def main():
    ap = argparse.ArgumentParser(description="Merge application records into the tracker and ledger")
    ap.add_argument("--tracker", default=DEFAULT_TRACKER)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--no-ledger-sync", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read()
    incoming = json.loads(raw) if raw.strip() else []

    existing = parse_tracker(args.tracker)
    before = len(existing)
    merged = merge(existing, incoming)
    os.makedirs(os.path.dirname(args.tracker), exist_ok=True)
    render(merged, args.tracker)
    print(f"tracker: {before} existing + {len(incoming)} incoming -> {len(merged)} roles", file=sys.stderr)

    if not args.no_ledger_sync:
        n = sync_ledger(incoming, args.ledger)
        print(f"ledger: {n} rows synced", file=sys.stderr)


if __name__ == "__main__":
    main()
