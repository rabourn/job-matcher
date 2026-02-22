#!/usr/bin/env python3
"""Normalize job listings from various API sources into a unified JSON schema.

Usage:
    cat api_output.json | python3 normalize-jobs.py --source greenhouse
    python3 normalize-jobs.py --source remotive < api_output.json

Reads JSON from stdin, writes normalized JSON array to stdout.
"""

import argparse
import json
import sys
import hashlib
from datetime import datetime
from html.parser import HTMLParser
from io import StringIO


class HTMLStripper(HTMLParser):
    """Strip HTML tags, keeping only text content."""

    def __init__(self):
        super().__init__()
        self.result = StringIO()

    def handle_data(self, data):
        self.result.write(data)

    def handle_entityref(self, name):
        entities = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
        self.result.write(entities.get(name, f"&{name};"))

    def handle_charref(self, name):
        try:
            if name.startswith("x"):
                char = chr(int(name[1:], 16))
            else:
                char = chr(int(name))
            self.result.write(char)
        except (ValueError, OverflowError):
            pass

    def get_text(self):
        return self.result.getvalue().strip()


def strip_html(html_string):
    """Remove HTML tags from a string."""
    if not html_string:
        return ""
    stripper = HTMLStripper()
    try:
        stripper.feed(str(html_string))
    except Exception:
        return str(html_string)
    return stripper.get_text()


def make_id(source, *parts):
    """Generate a deterministic ID from source + key fields."""
    key = f"{source}:" + ":".join(str(p) for p in parts if p)
    return hashlib.md5(key.encode()).hexdigest()[:12]


def infer_seniority(title):
    """Infer seniority level from job title."""
    title_lower = (title or "").lower()
    if any(w in title_lower for w in ["chief", "cto", "ceo", "cfo", "coo", "c-suite", "vp ", "vice president"]):
        return "executive"
    if any(w in title_lower for w in ["director", "head of", "head,", "principal"]):
        return "director"
    if any(w in title_lower for w in ["senior", "sr.", "sr ", "lead", "staff", "manager"]):
        return "senior"
    if any(w in title_lower for w in ["junior", "jr.", "jr ", "entry", "associate", "intern", "graduate"]):
        return "junior"
    return "mid"


def infer_work_mode(location_str, remote_flag=None):
    """Infer work mode from location string and/or remote flag."""
    if remote_flag is True:
        return "remote"
    loc = (location_str or "").lower()
    if "remote" in loc and ("hybrid" in loc or "onsite" in loc or "office" in loc):
        return "hybrid"
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    return "onsite"


def normalize_greenhouse(data):
    """Normalize Greenhouse API response."""
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    results = []
    for job in jobs:
        loc_parts = []
        for loc in job.get("location", {}).get("name", "").split(","):
            loc_parts.append(loc.strip())
        location = job.get("location", {}).get("name", "")
        departments = [d.get("name", "") for d in job.get("departments", [])]
        posted = job.get("updated_at") or job.get("first_published_at", "")
        # Greenhouse content is in job.content (HTML)
        content = strip_html(job.get("content", ""))
        results.append({
            "id": make_id("greenhouse", job.get("id")),
            "source": "greenhouse",
            "source_id": str(job.get("id", "")),
            "title": job.get("title", ""),
            "company": job.get("company_name", "") or job.get("board_name", ""),
            "location": location,
            "remote": "remote" in location.lower(),
            "work_mode": infer_work_mode(location),
            "employment_type": "",
            "seniority": infer_seniority(job.get("title", "")),
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "posted_date": posted[:10] if posted else "",
            "description_text": content,
            "url": job.get("absolute_url", ""),
            "apply_url": job.get("absolute_url", ""),
            "departments": departments,
            "tags": [],
            "verification_status": "GUARANTEED",
        })
    return results


def normalize_lever(data):
    """Normalize Lever API response."""
    jobs = data if isinstance(data, list) else []
    results = []
    for job in jobs:
        categories = job.get("categories", {})
        location = categories.get("location", "") or ""
        commitment = categories.get("commitment", "") or ""
        team = categories.get("team", "") or ""
        department = categories.get("department", "") or ""
        posted_ms = job.get("createdAt", 0)
        posted = datetime.fromtimestamp(posted_ms / 1000).strftime("%Y-%m-%d") if posted_ms else ""
        desc_parts = []
        for lst in job.get("lists", []):
            desc_parts.append(lst.get("text", ""))
            desc_parts.append(strip_html(lst.get("content", "")))
        description = job.get("descriptionPlain", "") or strip_html(job.get("description", ""))
        if desc_parts:
            description += "\n" + "\n".join(desc_parts)
        results.append({
            "id": make_id("lever", job.get("id")),
            "source": "lever",
            "source_id": str(job.get("id", "")),
            "title": job.get("text", ""),
            "company": job.get("company", "") or "",
            "location": location,
            "remote": "remote" in location.lower(),
            "work_mode": infer_work_mode(location),
            "employment_type": commitment,
            "seniority": infer_seniority(job.get("text", "")),
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "posted_date": posted,
            "description_text": description,
            "url": job.get("hostedUrl", "") or job.get("applyUrl", ""),
            "apply_url": job.get("applyUrl", "") or job.get("hostedUrl", ""),
            "departments": [d for d in [department, team] if d],
            "tags": [categories.get("allLocations", "")],
            "verification_status": "GUARANTEED",
        })
    return results


def normalize_workable(data):
    """Normalize Workable widget API response."""
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    results = []
    for job in jobs:
        location = job.get("location", "") or job.get("city", "") or ""
        if job.get("country"):
            location = f"{location}, {job['country']}" if location else job["country"]
        results.append({
            "id": make_id("workable", job.get("shortcode") or job.get("id")),
            "source": "workable",
            "source_id": str(job.get("shortcode", "") or job.get("id", "")),
            "title": job.get("title", ""),
            "company": job.get("company", "") or "",
            "location": location,
            "remote": job.get("telecommuting", False) or "remote" in location.lower(),
            "work_mode": "remote" if job.get("telecommuting") else infer_work_mode(location),
            "employment_type": job.get("employment_type", ""),
            "seniority": infer_seniority(job.get("title", "")),
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "posted_date": (job.get("published_on") or job.get("created_at", ""))[:10],
            "description_text": strip_html(job.get("description", "")),
            "url": job.get("url", "") or job.get("application_url", ""),
            "apply_url": job.get("application_url", "") or job.get("url", ""),
            "departments": [job.get("department", "")] if job.get("department") else [],
            "tags": [],
            "verification_status": "GUARANTEED",
        })
    return results


def normalize_ashby(data):
    """Normalize Ashby posting API response."""
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    results = []
    for job in jobs:
        location = job.get("location", "") or ""
        if isinstance(location, dict):
            location = location.get("name", "") or ""
        compensation = job.get("compensation", {}) or {}
        salary_min = None
        salary_max = None
        salary_currency = None
        if compensation:
            salary_range = compensation.get("range", {}) or {}
            salary_min = salary_range.get("min")
            salary_max = salary_range.get("max")
            salary_currency = compensation.get("currency")
        department = job.get("department", "") or ""
        if isinstance(department, dict):
            department = department.get("name", "") or ""
        results.append({
            "id": make_id("ashby", job.get("id")),
            "source": "ashby",
            "source_id": str(job.get("id", "")),
            "title": job.get("title", ""),
            "company": job.get("organizationName", "") or "",
            "location": location,
            "remote": job.get("isRemote", False) or "remote" in str(location).lower(),
            "work_mode": "remote" if job.get("isRemote") else infer_work_mode(str(location)),
            "employment_type": job.get("employmentType", ""),
            "seniority": infer_seniority(job.get("title", "")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "posted_date": (job.get("publishedDate") or job.get("updatedAt", ""))[:10] if job.get("publishedDate") or job.get("updatedAt") else "",
            "description_text": strip_html(job.get("descriptionHtml", "") or job.get("description", "")),
            "url": job.get("jobUrl", "") or job.get("applyUrl", ""),
            "apply_url": job.get("applyUrl", "") or job.get("jobUrl", ""),
            "departments": [department] if department else [],
            "tags": [t.get("name", "") if isinstance(t, dict) else str(t) for t in (job.get("tags", []) or [])],
            "verification_status": "GUARANTEED",
        })
    return results


def normalize_remotive(data):
    """Normalize Remotive API response."""
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    results = []
    for job in jobs:
        salary_str = job.get("salary", "") or ""
        salary_min = None
        salary_max = None
        # Remotive sometimes includes salary as a range string
        results.append({
            "id": make_id("remotive", job.get("id")),
            "source": "remotive",
            "source_id": str(job.get("id", "")),
            "title": job.get("title", ""),
            "company": job.get("company_name", ""),
            "location": job.get("candidate_required_location", "") or "Remote",
            "remote": True,
            "work_mode": "remote",
            "employment_type": job.get("job_type", ""),
            "seniority": infer_seniority(job.get("title", "")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": None,
            "posted_date": (job.get("publication_date") or "")[:10],
            "description_text": strip_html(job.get("description", "")),
            "url": job.get("url", ""),
            "apply_url": job.get("url", ""),
            "departments": [job.get("category", "")] if job.get("category") else [],
            "tags": job.get("tags", []) or [],
            "verification_status": "API_ACTIVE",
        })
    return results


def normalize_remoteok(data):
    """Normalize RemoteOK API response (skip element[0] which is metadata)."""
    jobs = data[1:] if isinstance(data, list) and len(data) > 1 else data if isinstance(data, list) else []
    results = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        salary_min = None
        salary_max = None
        if job.get("salary_min"):
            try:
                salary_min = int(job["salary_min"])
            except (ValueError, TypeError):
                pass
        if job.get("salary_max"):
            try:
                salary_max = int(job["salary_max"])
            except (ValueError, TypeError):
                pass
        results.append({
            "id": make_id("remoteok", job.get("id")),
            "source": "remoteok",
            "source_id": str(job.get("id", "")),
            "title": job.get("position", ""),
            "company": job.get("company", ""),
            "location": job.get("location", "") or "Remote",
            "remote": True,
            "work_mode": "remote",
            "employment_type": "",
            "seniority": infer_seniority(job.get("position", "")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": "USD" if salary_min else None,
            "posted_date": (job.get("date") or "")[:10],
            "description_text": strip_html(job.get("description", "")),
            "url": job.get("url", ""),
            "apply_url": job.get("apply_url", "") or job.get("url", ""),
            "departments": [],
            "tags": job.get("tags", []) or [],
            "verification_status": "API_ACTIVE",
        })
    return results


def normalize_jobicy(data):
    """Normalize Jobicy API response."""
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    results = []
    for job in jobs:
        salary_min = None
        salary_max = None
        salary_currency = None
        # Jobicy uses salaryMin/salaryMax or annualSalaryMin/annualSalaryMax
        for min_key in ["salaryMin", "annualSalaryMin", "salary_min"]:
            if job.get(min_key):
                try:
                    salary_min = int(job[min_key])
                    break
                except (ValueError, TypeError):
                    pass
        for max_key in ["salaryMax", "annualSalaryMax", "salary_max"]:
            if job.get(max_key):
                try:
                    salary_max = int(job[max_key])
                    break
                except (ValueError, TypeError):
                    pass
        if salary_min or salary_max:
            salary_currency = job.get("salaryCurrency", "USD")
        results.append({
            "id": make_id("jobicy", job.get("id")),
            "source": "jobicy",
            "source_id": str(job.get("id", "")),
            "title": strip_html(job.get("jobTitle", "")),
            "company": job.get("companyName", ""),
            "location": job.get("jobGeo", "") or "Remote",
            "remote": True,
            "work_mode": "remote",
            "employment_type": job.get("jobType", ""),
            "seniority": infer_seniority(job.get("jobTitle", "")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "posted_date": (job.get("pubDate") or "")[:10],
            "description_text": strip_html(job.get("jobDescription", "")),
            "url": job.get("url", ""),
            "apply_url": job.get("url", ""),
            "departments": job.get("jobIndustry") if isinstance(job.get("jobIndustry"), list) else [job.get("jobIndustry", "")] if job.get("jobIndustry") else [],
            "tags": job.get("jobIndustry", []) if isinstance(job.get("jobIndustry"), list) else [job.get("jobIndustry", "")] if job.get("jobIndustry") else [],
            "verification_status": "API_ACTIVE",
        })
    return results


def normalize_himalayas(data):
    """Normalize Himalayas API response."""
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    results = []
    for job in jobs:
        salary_min = None
        salary_max = None
        salary_currency = None
        comp = job.get("companySlug", "")
        if job.get("minSalary"):
            try:
                salary_min = int(job["minSalary"])
            except (ValueError, TypeError):
                pass
        if job.get("maxSalary"):
            try:
                salary_max = int(job["maxSalary"])
            except (ValueError, TypeError):
                pass
        if salary_min or salary_max:
            salary_currency = "USD"
        results.append({
            "id": make_id("himalayas", job.get("id") or job.get("slug")),
            "source": "himalayas",
            "source_id": str(job.get("id", "") or job.get("slug", "")),
            "title": job.get("title", ""),
            "company": job.get("companyName", ""),
            "location": job.get("locationRestrictions", "") or "Remote",
            "remote": True,
            "work_mode": "remote",
            "employment_type": job.get("type", ""),
            "seniority": job.get("seniority", "") or infer_seniority(job.get("title", "")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "posted_date": (job.get("pubDate") or job.get("postedDate", ""))[:10] if job.get("pubDate") or job.get("postedDate") else "",
            "description_text": strip_html(job.get("description", "")),
            "url": job.get("applicationUrl", "") or f"https://himalayas.app/jobs/{job.get('slug', '')}",
            "apply_url": job.get("applicationUrl", "") or f"https://himalayas.app/jobs/{job.get('slug', '')}",
            "departments": [job.get("category", "")] if job.get("category") else [],
            "tags": job.get("tags", []) or [],
            "verification_status": "API_ACTIVE",
        })
    return results


def normalize_themuse(data):
    """Normalize The Muse API response."""
    jobs = data.get("results", []) if isinstance(data, dict) else data
    results = []
    for job in jobs:
        locations = job.get("locations", [])
        loc_names = [loc.get("name", "") for loc in locations if isinstance(loc, dict)]
        location = ", ".join(loc_names) if loc_names else ""
        company = job.get("company", {})
        company_name = company.get("name", "") if isinstance(company, dict) else str(company)
        levels = job.get("levels", [])
        level_names = [lv.get("name", "") for lv in levels if isinstance(lv, dict)]
        categories = job.get("categories", [])
        cat_names = [c.get("name", "") for c in categories if isinstance(c, dict)]
        results.append({
            "id": make_id("themuse", job.get("id")),
            "source": "themuse",
            "source_id": str(job.get("id", "")),
            "title": job.get("name", ""),
            "company": company_name,
            "location": location,
            "remote": "flexible" in location.lower() or "remote" in location.lower(),
            "work_mode": infer_work_mode(location),
            "employment_type": "",
            "seniority": level_names[0] if level_names else infer_seniority(job.get("name", "")),
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "posted_date": (job.get("publication_date") or "")[:10],
            "description_text": strip_html(job.get("contents", "")),
            "url": job.get("refs", {}).get("landing_page", ""),
            "apply_url": job.get("refs", {}).get("landing_page", ""),
            "departments": cat_names,
            "tags": [],
            "verification_status": "API_ACTIVE",
        })
    return results


def normalize_rss(data):
    """Normalize RSS feed items (already converted to JSON by fetch-rss.sh)."""
    items = data.get("items", []) if isinstance(data, dict) else data
    results = []
    for item in items:
        results.append({
            "id": make_id("rss", item.get("link") or item.get("title")),
            "source": "rss",
            "source_id": item.get("guid", "") or item.get("link", ""),
            "title": item.get("title", ""),
            "company": item.get("company", "") or item.get("author", ""),
            "location": item.get("location", "") or "",
            "remote": "remote" in (item.get("title", "") + item.get("location", "")).lower(),
            "work_mode": infer_work_mode(item.get("location", "") or item.get("title", "")),
            "employment_type": "",
            "seniority": infer_seniority(item.get("title", "")),
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "posted_date": (item.get("pubDate") or item.get("published", ""))[:10] if item.get("pubDate") or item.get("published") else "",
            "description_text": strip_html(item.get("description", "") or item.get("summary", "")),
            "url": item.get("link", ""),
            "apply_url": item.get("link", ""),
            "departments": [item.get("category", "")] if item.get("category") else [],
            "tags": item.get("categories", []) or [],
            "verification_status": "UNVERIFIED",
        })
    return results


NORMALIZERS = {
    "greenhouse": normalize_greenhouse,
    "lever": normalize_lever,
    "workable": normalize_workable,
    "ashby": normalize_ashby,
    "remotive": normalize_remotive,
    "remoteok": normalize_remoteok,
    "jobicy": normalize_jobicy,
    "himalayas": normalize_himalayas,
    "themuse": normalize_themuse,
    "rss": normalize_rss,
}


def main():
    parser = argparse.ArgumentParser(description="Normalize job listings to a unified schema")
    parser.add_argument("--source", required=True, choices=list(NORMALIZERS.keys()),
                        help="Source API format")
    parser.add_argument("--company", default="",
                        help="Company name (used for ATS sources where company isn't in the API response)")
    args = parser.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        json.dump([], sys.stdout, indent=2)
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        sys.exit(1)

    normalizer = NORMALIZERS[args.source]
    results = normalizer(data)

    # Backfill company name from --company flag if not in API data
    if args.company:
        for job in results:
            if not job["company"]:
                job["company"] = args.company

    json.dump(results, sys.stdout, indent=2, default=str)


if __name__ == "__main__":
    main()
