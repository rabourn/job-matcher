#!/usr/bin/env python3
"""Parse LinkedIn job alert emails into the normalized job schema.

Usage:
    cat thread.json | python3 parse-alert-email.py            # Gmail get_thread JSON
    cat body.txt | python3 parse-alert-email.py --text        # raw plaintext body
    python3 parse-alert-email.py --text < body.txt

Reads from stdin, writes a normalized JSON array (same schema as
normalize-jobs.py) to stdout.

Works on the email's plaintext body, not the HTML: LinkedIn's digest emails
carry a parallel text/plain part with a regular card structure (title /
company / location / boilerplate / "View job: URL") which is far more stable
than the ~200KB tracking-laden HTML.

Per the PRD, the LinkedIn URL is provenance only. It is stored in
`linkedin_url` (stripped of tracking parameters) and must never be fetched
or treated as a data source. `posted_date` is left empty on purpose: email
metadata is not trusted for freshness; the resolve stage fills it from the
canonical source.
"""

import argparse
import json
import re
import sys
import hashlib

FOOTER_MARKERS = (
    "See all jobs on LinkedIn:",
    "Manage your job alerts:",
    "This email was intended for",
)

# Card lines that are boilerplate, never title/company/location data.
BOILERPLATE_PATTERNS = [
    re.compile(r"^this company is actively hiring$", re.I),
    re.compile(r"^actively recruiting$", re.I),
    re.compile(r"^apply with resume & profile$", re.I),
    re.compile(r"^be an early applicant$", re.I),
    re.compile(r"^\d+\s+connections?$", re.I),
    re.compile(r"^\d+\s+school alumni$", re.I),
    re.compile(r"^\d+\s+company alumni$", re.I),
    re.compile(r"^your profile matches this job$", re.I),
    re.compile(r"^posted on \d", re.I),
    re.compile(r"^easy apply$", re.I),
]

JOB_ID_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)")
VIEW_JOB_RE = re.compile(r"^view job:\s*(\S+)", re.I)
ALERT_HEADER_RE = re.compile(r"^your job alert for\s+(.*)$", re.I)

WORK_MODE_HINTS = [
    (re.compile(r"\bremote\b", re.I), "remote"),
    (re.compile(r"\bhybrid\b", re.I), "hybrid"),
    (re.compile(r"\bon-?site\b", re.I), "onsite"),
]


def make_id(source, *parts):
    """Deterministic ID, same recipe as normalize-jobs.py."""
    key = f"{source}:" + ":".join(str(p) for p in parts if p)
    return hashlib.md5(key.encode()).hexdigest()[:12]


SENIORITY_PATTERNS = [
    # Mirrors normalize-jobs.py. Word boundaries matter: plain substring
    # matching classified every "Director" title as executive ("direCTOr").
    ("executive", re.compile(r"\b(chief|cto|ceo|cfo|coo|c-suite|vp|svp|evp|vice president)\b")),
    ("director", re.compile(r"\b(director|head of|head,|principal)\b")),
    ("senior", re.compile(r"\b(senior|sr\.?|lead|staff|manager)\b")),
    ("junior", re.compile(r"\b(junior|jr\.?|entry|associate|intern|internship|graduate)\b")),
]


def infer_seniority(title):
    """Infer seniority level from job title (mirrors normalize-jobs.py)."""
    title_lower = (title or "").lower()
    for level, pattern in SENIORITY_PATTERNS:
        if pattern.search(title_lower):
            return level
    return "mid"


def is_boilerplate(line):
    return any(p.match(line.strip()) for p in BOILERPLATE_PATTERNS)


def infer_work_mode(*texts):
    for text in texts:
        for pattern, mode in WORK_MODE_HINTS:
            if pattern.search(text or ""):
                return mode
    return ""


def split_cards(body):
    """Split the plaintext body into (alert_terms, [card_lines]) chunks.

    Cards are separated by dashed-line rules. The footer (everything from the
    first footer marker on) is discarded.
    """
    lines = body.splitlines()
    alert_terms = ""
    cards = []
    current = []
    in_footer = False
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(m) for m in FOOTER_MARKERS):
            in_footer = True
        if in_footer:
            continue
        header_match = ALERT_HEADER_RE.match(stripped)
        if header_match:
            alert_terms = header_match.group(1).strip()
            continue
        if re.match(r"^-{5,}$", stripped):
            if current:
                cards.append(current)
                current = []
            continue
        if stripped:
            current.append(stripped)
    if current:
        cards.append(current)
    return alert_terms, cards


def parse_card(card_lines, alert_terms, email_date, email_subject):
    """Parse one job card's lines into a normalized job dict, or None."""
    view_url = ""
    data_lines = []
    extras = []
    for line in card_lines:
        m = VIEW_JOB_RE.match(line)
        if m:
            view_url = m.group(1)
            continue
        if line.startswith("http://") or line.startswith("https://"):
            if not view_url:
                view_url = line
            continue
        if is_boilerplate(line):
            extras.append(line)
            continue
        data_lines.append(line)

    if len(data_lines) < 2:
        return None  # not a job card (stray upsell or remnant)

    title = data_lines[0]
    company = data_lines[1]
    location = data_lines[2] if len(data_lines) > 2 else ""
    snippet = " | ".join(data_lines[3:] + extras)

    job_id_match = JOB_ID_RE.search(view_url)
    linkedin_job_id = job_id_match.group(1) if job_id_match else ""
    # Strip tracking: keep only the durable job-view form
    linkedin_url = f"https://www.linkedin.com/jobs/view/{linkedin_job_id}/" if linkedin_job_id else view_url

    return {
        "id": make_id("linkedin_alert", linkedin_job_id or f"{company}:{title}:{location}"),
        "source": "linkedin_alert",
        "source_id": linkedin_job_id,
        "title": title,
        "company": company,
        "location": location,
        "remote": infer_work_mode(title, location, snippet) == "remote",
        "work_mode": infer_work_mode(title, location, snippet) or "unknown",
        "employment_type": "",
        "seniority": infer_seniority(title),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "posted_date": "",  # never from the email; resolve stage fills this
        "description_text": snippet,
        "url": linkedin_url,
        "apply_url": "",  # filled by resolve stage with the canonical URL
        "departments": [],
        "tags": [],
        "verification_status": "UNVERIFIED",
        "linkedin_url": linkedin_url,
        "linkedin_job_id": linkedin_job_id,
        "alert_terms": alert_terms,
        "email_date": email_date,
        "email_subject": email_subject,
    }


def parse_body(body, email_date="", email_subject=""):
    alert_terms, cards = split_cards(body)
    jobs = []
    for card in cards:
        job = parse_card(card, alert_terms, email_date, email_subject)
        if job:
            jobs.append(job)
    return jobs


def extract_messages(data):
    """Yield (plaintext_body, date, subject) from Gmail tool JSON shapes:
    a get_thread result, a list of them, or a list of bare message objects."""
    if isinstance(data, list):
        for item in data:
            yield from extract_messages(item)
        return
    if not isinstance(data, dict):
        return
    if "messages" in data:
        for msg in data["messages"]:
            yield from extract_messages(msg)
        return
    if "threads" in data:
        for thread in data["threads"]:
            yield from extract_messages(thread)
        return
    body = data.get("plaintextBody") or data.get("plaintext_body") or ""
    if body:
        yield body, data.get("date", ""), data.get("subject", "")


def main():
    parser = argparse.ArgumentParser(description="Parse LinkedIn alert emails to normalized jobs")
    parser.add_argument("--text", action="store_true",
                        help="Treat stdin as a raw plaintext email body instead of Gmail JSON")
    args = parser.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        json.dump([], sys.stdout, indent=2)
        return

    jobs = []
    if args.text:
        jobs = parse_body(raw)
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}", file=sys.stderr)
            sys.exit(1)
        for body, date, subject in extract_messages(data):
            jobs.extend(parse_body(body, date, subject))

    print(f"Parsed {len(jobs)} job cards", file=sys.stderr)
    json.dump(jobs, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
