#!/usr/bin/env python3
"""Regression test for parse-alert-email.py against the synthetic fixture.

Run:  python3 test/test_parse_alert_email.py
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "parse-alert-email.py")
FIXTURE = os.path.join(ROOT, "test", "fixtures", "linkedin-alert-digest.txt")


def run_parser(args, stdin_text):
    result = subprocess.run(
        [sys.executable, SCRIPT] + args,
        input=stdin_text, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def main():
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  ok: {name}")
        else:
            failures.append(name)
            print(f"  FAIL: {name} {detail}")

    with open(FIXTURE) as fh:
        body = fh.read()

    jobs = run_parser(["--text"], body)

    print("Fixture: linkedin-alert-digest.txt")
    check("parses 4 job cards", len(jobs) == 4, f"(got {len(jobs)})")

    by_id = {j["linkedin_job_id"]: j for j in jobs}
    check("all job IDs extracted", set(by_id) == {"1000000001", "1000000002", "1000000003", "1000000004"})

    j1 = by_id.get("1000000001", {})
    check("title", j1.get("title") == "Head of Product, Climate Platform")
    check("company", j1.get("company") == "Verdant Analytics")
    check("location", j1.get("location") == "Dubai, United Arab Emirates")
    check("tracking params stripped",
          j1.get("linkedin_url") == "https://www.linkedin.com/jobs/view/1000000001/")
    check("posted_date empty (never from email)", j1.get("posted_date") == "")
    check("verification UNVERIFIED", j1.get("verification_status") == "UNVERIFIED")
    check("alert terms captured", j1.get("alert_terms") == "Design Strategist or Product Manager in MENA")

    j2 = by_id.get("1000000002", {})
    check("remote inferred from location", j2.get("work_mode") == "remote" and j2.get("remote") is True)
    check("director seniority", j2.get("seniority") == "director")

    j3 = by_id.get("1000000003", {})
    check("boilerplate without blank line filtered",
          j3.get("company") == "Brightline Studio" and j3.get("location") == "Singapore")

    j4 = by_id.get("1000000004", {})
    check("hybrid inferred from title", j4.get("work_mode") == "hybrid")
    check("footer/upsell produced no phantom cards",
          all("Stand out" not in j.get("title", "") for j in jobs))

    # Gmail JSON input shape
    thread_json = json.dumps({"id": "t1", "messages": [{
        "plaintextBody": body, "date": "2026-06-11T15:41:44Z", "subject": "Test digest",
    }]})
    jobs_json = run_parser([], thread_json)
    check("Gmail thread JSON input", len(jobs_json) == 4)
    check("email metadata attached", jobs_json[0].get("email_date") == "2026-06-11T15:41:44Z")

    # Empty input
    empty = run_parser(["--text"], "")
    check("empty input gives empty array", empty == [])

    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed")


if __name__ == "__main__":
    main()
