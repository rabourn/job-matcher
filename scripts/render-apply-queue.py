#!/usr/bin/env python3
"""Render the vault apply queue deterministically from the ledger.

Usage:
    python3 render-apply-queue.py            # uses data/pipeline.local.json
    python3 render-apply-queue.py --out PATH --ledger PATH

The apply queue is the contract with Recall's daily note, which parses
`## {Title}: {Company}` headings and `- [x]` checkboxes (see
docs/recall-integration.md). Generating it from the ledger with a script
guarantees that format instead of leaving it to the scoring agent, which
formatted it as "Company: Title" and broke the daily-note line. Mechanical
output belongs in code.

Renders every Tier 1 reported role: heading, score, posted/verification,
canonical link, report wiki-link, absolute CV draft path, and the two
checkboxes a role stays pending until one is ticked.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    for name in ("pipeline.local.json", "pipeline.example.json"):
        p = os.path.join(ROOT, "data", name)
        if os.path.exists(p):
            with open(p) as fh:
                return json.load(fh)
    return {}


def expand(p):
    return os.path.expanduser(p) if p else p


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Render apply-queue.md from the ledger")
    ap.add_argument("--out", default=expand(cfg.get("vault_apply_queue", "~/cairn/career/apply-queue.md")))
    ap.add_argument("--ledger", default=os.path.join(ROOT, cfg.get("ledger_path", "data/ledger.db")))
    ap.add_argument("--tier", type=int, default=1)
    args = ap.parse_args()

    conn = sqlite3.connect(args.ledger)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT company, title, score, canonical_url, posted_date, source_type, cv_path, report_path "
        "FROM jobs WHERE status='reported' AND tier=? ORDER BY score DESC",
        (args.tier,),
    ).fetchall()
    conn.close()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = ["---", "type: apply-queue", f"updated: {today}", "---", "", "# Apply queue", ""]
    if not rows:
        out.append("No pending applications. The screen-alerts pipeline refreshes this "
                   "file on each run; Tier 1 roles with tailored CV drafts appear here.")
    else:
        out.append(f"{len(rows)} Tier 1 role(s). Each CV is a tailored DRAFT: open in "
                   "InDesign, check for overset text, then submit yourself.")
        out.append("")
        for r in rows:
            posted = r["posted_date"] or "no date on canonical source"
            out.append(f"## {r['title']}: {r['company']}")
            out.append("")
            out.append(f"- Score: {r['score']} (Tier 1)")
            out.append(f"- Posted: {posted} · verified via {r['source_type'] or 'unknown'}")
            if r["canonical_url"]:
                out.append(f"- Apply: {r['canonical_url']}")
            if r["report_path"]:
                stem = os.path.splitext(os.path.basename(r["report_path"]))[0]
                out.append(f"- Report: [[{stem}]]")
            if r["cv_path"]:
                out.append(f"- CV draft: {os.path.join(ROOT, r['cv_path'])}")
            out.append("- [ ] applied")
            out.append("- [ ] skipped")
            out.append("")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")
    print(f"apply queue rendered: {len(rows)} Tier 1 role(s) -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
