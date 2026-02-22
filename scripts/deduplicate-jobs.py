#!/usr/bin/env python3
"""Deduplicate job listings from multiple sources using fuzzy matching.

Usage:
    cat merged.json | python3 deduplicate-jobs.py
    python3 deduplicate-jobs.py < merged.json

When duplicates are found, prefers ATS sources (greenhouse, lever, workable, ashby)
over API sources, and API sources over RSS/unverified.

Reads normalized JSON from stdin, writes deduplicated JSON to stdout.
"""

import json
import re
import sys
from difflib import SequenceMatcher


# Source priority — lower number = higher priority (preferred when deduplicating)
SOURCE_PRIORITY = {
    "greenhouse": 1,
    "lever": 1,
    "workable": 1,
    "ashby": 1,
    "remotive": 2,
    "remoteok": 2,
    "jobicy": 2,
    "himalayas": 2,
    "themuse": 2,
    "rss": 3,
}


def normalize_company(name):
    """Normalize company name for comparison."""
    name = (name or "").lower().strip()
    # Remove common suffixes
    for suffix in [" inc", " inc.", " llc", " ltd", " ltd.", " gmbh", " pty", " co.", " corp", " corporation", " limited"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Remove punctuation
    name = re.sub(r'[^a-z0-9\s]', '', name)
    return name.strip()


def normalize_title(title):
    """Normalize job title for comparison."""
    title = (title or "").lower().strip()
    # Remove location info in parentheses
    title = re.sub(r'\([^)]*\)', '', title)
    # Remove common prefixes/suffixes
    title = re.sub(r'\b(remote|hybrid|onsite|full.?time|part.?time|contract)\b', '', title)
    # Collapse whitespace
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def fuzzy_match(a, b, threshold=0.75):
    """Check if two strings are similar enough to be considered the same."""
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def is_duplicate(job_a, job_b):
    """Determine if two jobs are likely duplicates."""
    comp_a = normalize_company(job_a.get("company", ""))
    comp_b = normalize_company(job_b.get("company", ""))
    title_a = normalize_title(job_a.get("title", ""))
    title_b = normalize_title(job_b.get("title", ""))

    # Company must match (fuzzy)
    if not fuzzy_match(comp_a, comp_b, 0.8):
        return False

    # Title must match (fuzzy)
    if not fuzzy_match(title_a, title_b, 0.75):
        return False

    return True


def merge_jobs(preferred, other):
    """Merge two duplicate job records, preferring the higher-priority source.

    Fills in missing fields from the lower-priority record.
    """
    merged = dict(preferred)
    # Fill in missing fields from the other record
    for key in ["salary_min", "salary_max", "salary_currency", "posted_date", "employment_type"]:
        if not merged.get(key) and other.get(key):
            merged[key] = other[key]
    # Merge tags
    existing_tags = set(str(t) for t in merged.get("tags", []))
    for tag in other.get("tags", []):
        if str(tag) not in existing_tags:
            merged.setdefault("tags", []).append(tag)
    # Note the alternate source
    alt_sources = merged.get("alternate_sources", [])
    alt_sources.append({
        "source": other.get("source", ""),
        "url": other.get("url", ""),
        "source_id": other.get("source_id", ""),
    })
    merged["alternate_sources"] = alt_sources
    return merged


def get_priority(job):
    """Get the deduplication priority for a job (lower = preferred)."""
    return SOURCE_PRIORITY.get(job.get("source", ""), 99)


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        json.dump([], sys.stdout, indent=2)
        return

    try:
        jobs = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not jobs:
        json.dump([], sys.stdout, indent=2)
        return

    # Sort by source priority so preferred sources are processed first
    jobs.sort(key=lambda j: get_priority(j))

    unique = []
    for job in jobs:
        found_dup = False
        for i, existing in enumerate(unique):
            if is_duplicate(job, existing):
                # Merge — keep the one with higher priority (lower number)
                if get_priority(job) < get_priority(existing):
                    unique[i] = merge_jobs(job, existing)
                else:
                    unique[i] = merge_jobs(existing, job)
                found_dup = True
                break
        if not found_dup:
            unique.append(job)

    # Re-sort by relevance score if available, then by source priority
    unique.sort(key=lambda j: (-j.get("preliminary_relevance_score", 0), get_priority(j)))

    stats = {
        "total_input": len(jobs),
        "total_output": len(unique),
        "duplicates_removed": len(jobs) - len(unique),
    }
    print(f"Dedup stats: {json.dumps(stats)}", file=sys.stderr)

    json.dump(unique, sys.stdout, indent=2, default=str)


if __name__ == "__main__":
    main()
