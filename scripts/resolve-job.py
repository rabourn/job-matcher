#!/usr/bin/env python3
"""Resolve alert-sourced jobs to their canonical ATS posting.

Usage:
    cat alert-jobs.json | python3 resolve-job.py
    cat alert-jobs.json | python3 resolve-job.py --target-companies data/target-companies.local.json

For each job (normalized schema, e.g. from parse-alert-email.py), tries to find
the same role on the employer's own ATS:

1. Known slug: if the company appears in target-companies.json(.local), scan
   that ATS directly.
2. Slug guessing: derive candidate slugs from the company name (joined,
   hyphenated, first-word) and probe Greenhouse, Lever, Ashby, and Workable
   via the existing scan-*.sh scripts.
3. Fuzzy title match (SequenceMatcher >= 0.75, same threshold as
   deduplicate-jobs.py) against the ATS board's openings.

On a match, the job gains: canonical_url, posted_date (from the ATS, never the
email), source_type "ats", resolved_ats, resolved_slug, and
verification_status GUARANTEED. Unmatched jobs pass through unchanged with
source_type "unverified" so downstream stages can try free APIs or web search.

ATS boards are fetched once per (ats, slug) pair and cached for the run, so
ten alert jobs at one company cost one API call, and probing is skipped for
slugs already known not to exist.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from difflib import SequenceMatcher
from html.parser import HTMLParser
from io import StringIO

WORKDAY_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = StringIO()

    def handle_data(self, data):
        self.out.write(data)


def strip_html(s):
    p = _Stripper()
    try:
        p.feed(s or "")
    except Exception:
        return s or ""
    return " ".join(p.out.getvalue().split())


def fetch_workday_description(external_url):
    """Fetch a Workday job's full description from its CXS detail endpoint.

    Transforms the public job URL
      https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{path}
    into the API detail URL
      https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}
    and returns the plain-text jobDescription, or "" on any failure.
    """
    if not external_url or "/en-US/" not in external_url or "myworkdayjobs.com" not in external_url:
        return ""
    try:
        host_part, rest = external_url.split("/en-US/", 1)
        tenant = host_part.split("//", 1)[1].split(".", 1)[0]
        detail_url = f"{host_part}/wday/cxs/{tenant}/{rest}"
        req = urllib.request.Request(detail_url, headers={"User-Agent": WORKDAY_UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return strip_html(data.get("jobPostingInfo", {}).get("jobDescription", ""))
    except Exception as e:
        print(f"WORKDAY DETAIL FAILED {external_url[:60]} ({type(e).__name__})", file=sys.stderr)
        return ""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

ATS_ORDER = ["greenhouse", "lever", "ashby", "workable"]
TITLE_MATCH_THRESHOLD = 0.75

# Job-board aggregators that host other companies' postings on their own ATS.
# A title match on these boards is not canonical employer verification (the
# real employer and ATS are elsewhere), so never treat them as resolved.
AGGREGATOR_SLUGS = {"jobgether", "remoteok", "weworkremotely", "remotive", "workatastartup"}

# Suffixes that appear in alert-email company names but rarely in ATS slugs.
COMPANY_NOISE = re.compile(
    r"\b(middle east|mena|emea|apac|uk|usa|global|group|inc|llc|ltd|gmbh|corp|corporation|limited)\b",
    re.I,
)


def normalize_title(title):
    """Mirrors deduplicate-jobs.py."""
    title = (title or "").lower().strip()
    title = re.sub(r"\([^)]*\)", "", title)
    title = re.sub(r"\b(remote|hybrid|onsite|full.?time|part.?time|contract)\b", "", title)
    return re.sub(r"\s+", " ", title).strip()


def title_similarity(a, b):
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def slug_candidates(company):
    """Generate plausible ATS slugs for a company name, most specific first."""
    base = COMPANY_NOISE.sub(" ", company or "")
    base = re.sub(r"[^a-zA-Z0-9\s]", "", base).strip().lower()
    words = base.split()
    if not words:
        return []
    candidates = ["".join(words), "-".join(words)]
    if len(words) > 1:
        candidates.append(words[0])
    # Also try the raw name without noise-word stripping (e.g. "GovTech Singapore")
    raw = re.sub(r"[^a-zA-Z0-9\s]", "", (company or "")).strip().lower().split()
    if raw and "".join(raw) not in candidates:
        candidates.insert(0, "".join(raw))
    seen = set()
    return [c for c in candidates if c and not (c in seen or seen.add(c))]


def fetch_board(ats, slug, cache):
    """Fetch and normalize one ATS board, with per-run caching.

    Returns a list of normalized jobs, or [] if the board doesn't exist.
    """
    key = (ats, slug)
    if key in cache:
        return cache[key]
    # Greenhouse omits job descriptions unless ?content=true; without this the
    # scorer only sees titles. One call returns full content for every posting.
    scan_args = [os.path.join(SCRIPTS, f"scan-{ats}.sh"), slug]
    if ats == "greenhouse":
        scan_args.append("--content")
    try:
        scan = subprocess.run(
            scan_args,
            capture_output=True, text=True, timeout=45,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        # A hung or failing probe means "no usable board", never a crashed run.
        print(f"PROBE FAILED {ats}:{slug} ({type(e).__name__})", file=sys.stderr)
        cache[key] = []
        return []
    jobs = []
    if scan.returncode == 0 and scan.stdout.strip():
        norm = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "normalize-jobs.py"), "--source", ats],
            input=scan.stdout, capture_output=True, text=True,
        )
        if norm.returncode == 0 and norm.stdout.strip():
            try:
                jobs = json.loads(norm.stdout)
            except json.JSONDecodeError:
                jobs = []
    cache[key] = jobs
    return jobs


def fetch_workday(tenant, title, cache):
    """Search a Workday tenant for a title, with per-run discovery caching.

    Cache stores (site, wd) per tenant after the first successful discovery
    (or None for tenants with no Workday board), so later jobs at the same
    company skip the robots.txt probing. Search results are per-title, so
    they are not cached themselves.
    """
    disc_key = ("workday-site", tenant)
    if cache.get(disc_key, "unset") is None:
        return []
    args = [os.path.join(SCRIPTS, "scan-workday.sh"), tenant, title]
    if disc_key in cache:
        site, wd = cache[disc_key]
        args += [site, wd]
    try:
        scan = subprocess.run(args, capture_output=True, text=True, timeout=90)
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"PROBE FAILED workday:{tenant} ({type(e).__name__})", file=sys.stderr)
        cache[disc_key] = None
        return []
    try:
        data = json.loads(scan.stdout) if scan.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {}
    if not data.get("site"):
        if disc_key not in cache:
            cache[disc_key] = None
        return []
    cache[disc_key] = (data["site"], data["wd"])
    norm = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "normalize-jobs.py"), "--source", "workday"],
        input=scan.stdout, capture_output=True, text=True,
    )
    if norm.returncode == 0 and norm.stdout.strip():
        try:
            return json.loads(norm.stdout)
        except json.JSONDecodeError:
            return []
    return []


def load_known_companies(paths):
    """Map normalized company name -> (ats, slug) from target-companies files."""
    known = {}
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        for entry in data.get("companies", []):
            name_key = re.sub(r"[^a-z0-9]", "", entry.get("name", "").lower())
            if name_key and entry.get("ats") in ATS_ORDER and entry.get("slug"):
                known[name_key] = (entry["ats"], entry["slug"])
    return known


def resolve(job, known, cache, log):
    company = job.get("company", "")
    title = job.get("title", "")
    name_key = re.sub(r"[^a-z0-9]", "", company.lower())

    attempts = []
    if name_key in known:
        attempts.append(known[name_key])
    for slug in slug_candidates(company):
        for ats in ATS_ORDER:
            if (ats, slug) not in attempts:
                attempts.append((ats, slug))

    best = None
    best_score = 0.0
    best_meta = None
    for ats, slug in attempts:
        board = fetch_board(ats, slug, cache)
        if not board:
            continue
        for posting in board:
            score = title_similarity(title, posting.get("title", ""))
            if score > best_score:
                best, best_score, best_meta = posting, score, (ats, slug)
        # A live board that doesn't list the role is a meaningful signal;
        # keep probing other slugs/ATSes only if no good match yet.
        if best_score >= TITLE_MATCH_THRESHOLD:
            break

    # Workday last: heavier discovery, but it is where most enterprise
    # employers live (Mastercard, AstraZeneca, Zillow, ...).
    if best_score < TITLE_MATCH_THRESHOLD:
        for slug in slug_candidates(company):
            board = fetch_workday(slug, title, cache)
            for posting in board:
                score = title_similarity(title, posting.get("title", ""))
                if score > best_score:
                    best, best_score, best_meta = posting, score, ("workday", slug)
            if best_score >= TITLE_MATCH_THRESHOLD:
                break

    # An aggregator board match is not canonical employer verification.
    if best_meta and best_meta[1] in AGGREGATOR_SLUGS:
        log(f"AGGREGATOR {company} / {title} matched {best_meta[1]} board; not canonical, left unverified")
        best = None

    if best and best_score >= TITLE_MATCH_THRESHOLD:
        job["canonical_url"] = best.get("url", "")
        job["apply_url"] = best.get("apply_url", "") or best.get("url", "")
        job["posted_date"] = best.get("posted_date", "")
        job["source_type"] = "ats"
        job["resolved_ats"] = best_meta[0]
        job["resolved_slug"] = best_meta[1]
        job["resolved_title"] = best.get("title", "")
        job["title_match_score"] = round(best_score, 3)
        job["verification_status"] = "GUARANTEED"
        # Enrich from the canonical posting where the alert was thin. The
        # canonical description always wins when it is more substantial:
        # alert snippets are boilerplate at best.
        for field in ("location", "salary_min", "salary_max", "salary_currency"):
            if not job.get(field) and best.get(field):
                job[field] = best[field]
        if len(best.get("description_text") or "") > len(job.get("description_text") or ""):
            job["description_text"] = best["description_text"]
        if best.get("work_mode") and job.get("work_mode") in ("", "unknown"):
            job["work_mode"] = best["work_mode"]
            job["remote"] = best["work_mode"] == "remote"
        # Workday's search endpoint omits descriptions; fetch the matched
        # job's detail so scoring sees the full ad, not just the title.
        if best_meta[0] == "workday" and len(job.get("description_text") or "") < 200:
            detail = fetch_workday_description(best.get("url", ""))
            if detail:
                job["description_text"] = detail
        # Greenhouse returns HTML-escaped content, so one strip leaves literal
        # tags; re-strip when residual markup remains.
        desc = job.get("description_text") or ""
        if re.search(r"<[a-zA-Z/]", desc):
            job["description_text"] = strip_html(desc)
        if len(job.get("description_text") or "") < 200:
            job["thin_description"] = True  # scorer should flag, not invent
        log(f"RESOLVED {company} / {title} -> {best_meta[0]}:{best_meta[1]} (match {best_score:.2f}, desc {len(job.get('description_text') or '')} chars)")
    else:
        job["source_type"] = "unverified"
        job.setdefault("canonical_url", "")
        if best:
            log(f"NO MATCH {company} / {title} (best {best_score:.2f}: '{best.get('title','')}' on {best_meta[0]}:{best_meta[1]})")
        else:
            log(f"NO BOARD {company} / {title}")
    return job


def main():
    parser = argparse.ArgumentParser(description="Resolve alert jobs to canonical ATS postings")
    parser.add_argument("--target-companies", action="append", default=[],
                        help="target-companies JSON file(s); defaults to data/target-companies.json and .local.json")
    args = parser.parse_args()

    paths = args.target_companies or [
        os.path.join(ROOT, "data", "target-companies.json"),
        os.path.join(ROOT, "data", "target-companies.local.json"),
    ]
    known = load_known_companies(paths)

    raw = sys.stdin.read()
    jobs = json.loads(raw) if raw.strip() else []

    cache = {}
    log = lambda msg: print(msg, file=sys.stderr)
    resolved = [resolve(job, known, cache, log) for job in jobs]

    ats_count = sum(1 for j in resolved if j.get("source_type") == "ats")
    print(f"Resolved {ats_count}/{len(resolved)} jobs to ATS canonical postings", file=sys.stderr)
    json.dump(resolved, sys.stdout, indent=2, default=str)


if __name__ == "__main__":
    main()
