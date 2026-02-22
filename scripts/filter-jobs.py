#!/usr/bin/env python3
"""Filter and score normalized job listings by keywords, seniority, and work mode.

Usage:
    cat normalized.json | python3 filter-jobs.py --keywords "product,design,director" --seniority "senior,director" --remote-only
    python3 filter-jobs.py --keywords "data,ML,machine learning" --exclude-keywords "intern,junior" < jobs.json

Reads normalized JSON from stdin, writes filtered + scored JSON to stdout.
"""

import argparse
import json
import re
import sys


def tokenize(text):
    """Split text into lowercase words for matching."""
    return set(re.findall(r'\b[a-z][a-z0-9+#.-]{1,}\b', (text or "").lower()))


def keyword_score(job, keywords, exclude_keywords):
    """Score a job based on keyword matches in title and description.

    Title matches are weighted 3x higher than description matches.
    Returns a score from 0-100 and the list of matched keywords.
    """
    if not keywords:
        return 50, []  # neutral score if no keywords specified

    title = (job.get("title") or "").lower()
    desc = (job.get("description_text") or "").lower()
    company = (job.get("company") or "").lower()
    departments = " ".join(str(d) for d in (job.get("departments") or [])).lower()
    tags = " ".join(str(t) for t in (job.get("tags") or [])).lower()
    full_text = f"{title} {desc} {company} {departments} {tags}"

    # Check exclusions first
    if exclude_keywords:
        for kw in exclude_keywords:
            if kw.lower() in title:
                return -1, []  # hard exclude if keyword is in title

    matched = []
    title_hits = 0
    desc_hits = 0

    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower:
            continue
        if kw_lower in title:
            title_hits += 1
            matched.append(kw)
        elif kw_lower in full_text:
            desc_hits += 1
            matched.append(kw)

    if not matched:
        return 0, []

    # Title hits worth 3x description hits
    total_kw = len(keywords)
    raw_score = ((title_hits * 3) + desc_hits) / (total_kw * 3) * 100
    return min(round(raw_score, 1), 100), matched


def seniority_match(job_seniority, target_seniorities):
    """Check if job seniority matches any of the target levels."""
    if not target_seniorities:
        return True
    return (job_seniority or "").lower() in [s.lower() for s in target_seniorities]


def main():
    parser = argparse.ArgumentParser(description="Filter and score job listings")
    parser.add_argument("--keywords", default="",
                        help="Comma-separated keywords to match (e.g., 'product,design,UX')")
    parser.add_argument("--seniority", default="",
                        help="Comma-separated seniority levels to include (e.g., 'senior,director')")
    parser.add_argument("--remote-only", action="store_true",
                        help="Only include remote positions")
    parser.add_argument("--exclude-keywords", default="",
                        help="Comma-separated keywords to exclude")
    parser.add_argument("--min-score", type=float, default=0,
                        help="Minimum relevance score to include (0-100)")
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []
    seniorities = [s.strip() for s in args.seniority.split(",") if s.strip()] if args.seniority else []
    exclude_kw = [k.strip() for k in args.exclude_keywords.split(",") if k.strip()] if args.exclude_keywords else []

    raw = sys.stdin.read()
    if not raw.strip():
        json.dump([], sys.stdout, indent=2)
        return

    try:
        jobs = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        sys.exit(1)

    results = []
    for job in jobs:
        # Filter by remote
        if args.remote_only and not job.get("remote", False):
            continue

        # Filter by seniority
        if seniorities and not seniority_match(job.get("seniority", ""), seniorities):
            continue

        # Score by keywords
        score, matched_kw = keyword_score(job, keywords, exclude_kw)

        # Skip excluded jobs
        if score < 0:
            continue

        # Skip low-scoring jobs
        if score < args.min_score:
            continue

        job["preliminary_relevance_score"] = score
        job["matched_keywords"] = matched_kw
        results.append(job)

    # Sort by score descending
    results.sort(key=lambda j: j.get("preliminary_relevance_score", 0), reverse=True)

    json.dump(results, sys.stdout, indent=2, default=str)


if __name__ == "__main__":
    main()
