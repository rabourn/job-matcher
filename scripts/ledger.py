#!/usr/bin/env python3
"""SQLite ledger of every job the alert pipeline has seen.

Prevents repeat alerts for the same role from resurfacing as new, and tracks
each job's lifecycle: new -> reported -> applied / skipped / expired.

Usage:
    python3 ledger.py init [--db PATH]
    cat jobs.json | python3 ledger.py upsert [--db PATH]
    python3 ledger.py check --company "Acme" --title "Head of Product" --location "Remote"
    python3 ledger.py set-status --key KEY --status applied [--note "..."]
    python3 ledger.py queue [--status reported] [--tier 1]
    python3 ledger.py log-run [--db PATH]   (reads run stats JSON from stdin)
    python3 ledger.py expire --days 60      (mark stale 'new'/'reported' jobs expired)

`upsert` reads a normalized job array (the schema produced by normalize-jobs.py)
from stdin and writes the same array back to stdout with two fields added per job:
`ledger_key` and `ledger_status` ("new" for first-sighting jobs, otherwise the
stored status). Downstream stages use ledger_status to drop already-seen jobs.

Jobs are keyed on normalized company + title + location, the same normalization
rules as deduplicate-jobs.py, so the two layers agree on what "the same role" means.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ledger.db")

VALID_STATUSES = ["new", "reported", "applied", "skipped", "expired"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    times_seen INTEGER NOT NULL DEFAULT 1,
    score INTEGER,
    tier INTEGER,
    canonical_url TEXT DEFAULT '',
    source_type TEXT DEFAULT '',
    posted_date TEXT DEFAULT '',
    linkedin_url TEXT DEFAULT '',
    cv_path TEXT DEFAULT '',
    report_path TEXT DEFAULT '',
    note TEXT DEFAULT '',
    status_updated TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,
    finished TEXT,
    emails_reviewed INTEGER DEFAULT 0,
    jobs_extracted INTEGER DEFAULT 0,
    jobs_verified INTEGER DEFAULT 0,
    jobs_deduped INTEGER DEFAULT 0,
    jobs_skipped INTEGER DEFAULT 0,
    tier1_count INTEGER DEFAULT 0,
    cvs_generated INTEGER DEFAULT 0,
    outcome TEXT DEFAULT '',
    detail TEXT DEFAULT ''
);
"""


def normalize_company(name):
    """Normalize company name for keying (mirrors deduplicate-jobs.py)."""
    name = (name or "").lower().strip()
    for suffix in [" inc", " inc.", " llc", " ltd", " ltd.", " gmbh", " pty", " co.", " corp", " corporation", " limited"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    name = re.sub(r'[^a-z0-9\s]', '', name)
    return re.sub(r'\s+', ' ', name).strip()


def normalize_title(title):
    """Normalize job title for keying (mirrors deduplicate-jobs.py)."""
    title = (title or "").lower().strip()
    title = re.sub(r'\([^)]*\)', '', title)
    title = re.sub(r'\b(remote|hybrid|onsite|full.?time|part.?time|contract)\b', '', title)
    return re.sub(r'\s+', ' ', title).strip()


def normalize_location(location):
    """Normalize location for keying. Coarse on purpose: 'Remote - US' and
    'Remote (US)' should collide rather than create two ledger rows."""
    loc = (location or "").lower().strip()
    loc = re.sub(r'[^a-z0-9\s]', '', loc)
    return re.sub(r'\s+', ' ', loc).strip()


def make_key(company, title, location):
    return "|".join([normalize_company(company), normalize_title(title), normalize_location(location)])


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def cmd_init(args):
    conn = connect(args.db)
    conn.close()
    os.chmod(args.db, 0o600)
    print(f"Ledger initialized at {args.db}", file=sys.stderr)


def cmd_upsert(args):
    raw = sys.stdin.read()
    jobs = json.loads(raw) if raw.strip() else []
    conn = connect(args.db)
    ts = now_iso()
    new_count = seen_count = 0
    for job in jobs:
        key = make_key(job.get("company", ""), job.get("title", ""), job.get("location", ""))
        row = conn.execute("SELECT status FROM jobs WHERE key = ?", (key,)).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO jobs (key, company, title, location, status, first_seen, last_seen,
                                     canonical_url, source_type, posted_date, linkedin_url)
                   VALUES (?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?)""",
                (key, job.get("company", ""), job.get("title", ""), job.get("location", ""),
                 ts, ts, job.get("canonical_url", "") or job.get("url", ""),
                 job.get("source_type", "") or job.get("source", ""),
                 job.get("posted_date", ""), job.get("linkedin_url", "")),
            )
            job["ledger_status"] = "new"
            new_count += 1
        else:
            conn.execute("UPDATE jobs SET last_seen = ?, times_seen = times_seen + 1 WHERE key = ?", (ts, key))
            job["ledger_status"] = row["status"]
            seen_count += 1
        job["ledger_key"] = key
    conn.commit()
    conn.close()
    print(f"Ledger upsert: {new_count} new, {seen_count} previously seen", file=sys.stderr)
    json.dump(jobs, sys.stdout, indent=2, default=str)


def cmd_check(args):
    conn = connect(args.db)
    key = make_key(args.company, args.title, args.location or "")
    row = conn.execute("SELECT * FROM jobs WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row is None:
        json.dump({"key": key, "seen": False}, sys.stdout)
    else:
        json.dump({"key": key, "seen": True, **{k: row[k] for k in row.keys()}}, sys.stdout)


def cmd_set_status(args):
    if args.status not in VALID_STATUSES:
        print(f"Invalid status '{args.status}'. Valid: {', '.join(VALID_STATUSES)}", file=sys.stderr)
        sys.exit(1)
    conn = connect(args.db)
    fields = {"status": args.status, "status_updated": now_iso()}
    sets = "status = :status, status_updated = :status_updated"
    if args.note:
        sets += ", note = :note"
        fields["note"] = args.note
    if args.score is not None:
        sets += ", score = :score"
        fields["score"] = args.score
    if args.tier is not None:
        sets += ", tier = :tier"
        fields["tier"] = args.tier
    if args.cv_path:
        sets += ", cv_path = :cv_path"
        fields["cv_path"] = args.cv_path
    if args.report_path:
        sets += ", report_path = :report_path"
        fields["report_path"] = args.report_path
    if args.canonical_url:
        sets += ", canonical_url = :canonical_url"
        fields["canonical_url"] = args.canonical_url
    if args.source_type:
        sets += ", source_type = :source_type"
        fields["source_type"] = args.source_type
    if args.posted_date:
        sets += ", posted_date = :posted_date"
        fields["posted_date"] = args.posted_date
    fields["key"] = args.key
    cur = conn.execute(f"UPDATE jobs SET {sets} WHERE key = :key", fields)
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        print(f"No ledger row for key: {args.key}", file=sys.stderr)
        sys.exit(1)
    print(f"{args.key} -> {args.status}", file=sys.stderr)


def cmd_queue(args):
    conn = connect(args.db)
    sql = "SELECT * FROM jobs WHERE status = ?"
    params = [args.status]
    if args.tier is not None:
        sql += " AND tier = ?"
        params.append(args.tier)
    sql += " ORDER BY score DESC, last_seen DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    json.dump([{k: r[k] for k in r.keys()} for r in rows], sys.stdout, indent=2)


def cmd_log_run(args):
    raw = sys.stdin.read()
    stats = json.loads(raw) if raw.strip() else {}
    conn = connect(args.db)
    conn.execute(
        """INSERT INTO runs (started, finished, emails_reviewed, jobs_extracted, jobs_verified,
                             jobs_deduped, jobs_skipped, tier1_count, cvs_generated, outcome, detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (stats.get("started", now_iso()), stats.get("finished", now_iso()),
         stats.get("emails_reviewed", 0), stats.get("jobs_extracted", 0),
         stats.get("jobs_verified", 0), stats.get("jobs_deduped", 0),
         stats.get("jobs_skipped", 0), stats.get("tier1_count", 0),
         stats.get("cvs_generated", 0), stats.get("outcome", ""),
         json.dumps(stats.get("detail", ""), default=str) if not isinstance(stats.get("detail", ""), str) else stats.get("detail", "")),
    )
    conn.commit()
    conn.close()
    print("Run logged", file=sys.stderr)


def cmd_expire(args):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = connect(args.db)
    cur = conn.execute(
        "UPDATE jobs SET status = 'expired', status_updated = ? "
        "WHERE status IN ('new', 'reported') AND last_seen < ?",
        (now_iso(), cutoff),
    )
    conn.commit()
    conn.close()
    print(f"Expired {cur.rowcount} jobs not seen in {args.days} days", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Job pipeline SQLite ledger")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"Ledger path (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the ledger database")

    sub.add_parser("upsert", help="Upsert normalized jobs from stdin, annotate with ledger_status")

    p_check = sub.add_parser("check", help="Check whether a single job has been seen")
    p_check.add_argument("--company", required=True)
    p_check.add_argument("--title", required=True)
    p_check.add_argument("--location", default="")

    p_status = sub.add_parser("set-status", help="Update a job's status and metadata")
    p_status.add_argument("--key", required=True)
    p_status.add_argument("--status", required=True)
    p_status.add_argument("--note", default="")
    p_status.add_argument("--score", type=int)
    p_status.add_argument("--tier", type=int)
    p_status.add_argument("--cv-path", dest="cv_path", default="")
    p_status.add_argument("--report-path", dest="report_path", default="")
    p_status.add_argument("--canonical-url", dest="canonical_url", default="")
    p_status.add_argument("--source-type", dest="source_type", default="")
    p_status.add_argument("--posted-date", dest="posted_date", default="")

    p_queue = sub.add_parser("queue", help="List jobs by status (JSON to stdout)")
    p_queue.add_argument("--status", default="reported")
    p_queue.add_argument("--tier", type=int)

    sub.add_parser("log-run", help="Record run stats from stdin JSON")

    p_expire = sub.add_parser("expire", help="Mark stale new/reported jobs as expired")
    p_expire.add_argument("--days", type=int, default=60)

    args = parser.parse_args()
    {
        "init": cmd_init,
        "upsert": cmd_upsert,
        "check": cmd_check,
        "set-status": cmd_set_status,
        "queue": cmd_queue,
        "log-run": cmd_log_run,
        "expire": cmd_expire,
    }[args.command](args)


if __name__ == "__main__":
    main()
