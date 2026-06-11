
# PRD:  Job Alert Screening and Tailored CV Generator

**Owner:** Tanya Rabourn
**Status:** Draft v0.2
**Builds on:** job-matcher plugin v2.0 (github.com/rabourn/job-matcher)

## Purpose

Extend job-matcher with a scheduled pipeline that ingests LinkedIn job alert emails from Gmail, verifies each job against a canonical source, scores it against the career brief using the existing Phase 6 rubric, and generates a tailored IDML CV draft for the strongest matches.

## Why extend job-matcher instead of building a new script

job-matcher already contains the scoring rubric, dedup, normalization, filtering, and ATS scanners. The LinkedIn email is just a new lead source. Building this as a scanner module means:

1. One scoring system, one set of dealbreakers, one report format.
2. The existing ATS scanners (Greenhouse, Lever, Workable, Ashby) become the verification layer. LinkedIn blocks bots, but the same job almost always exists on the employer's own ATS, which is open, structured, and carries a real posted date.
3. The pipeline inherits the plugin's ATS-first philosophy: never trust aggregator metadata. A listing can claim "posted 12 days ago" while the canonical posting was removed months earlier. This failure mode was observed directly in testing.

## User

Tanya Rabourn, running locally on her Mac via Claude Code CLI in headless mode. Single user, personal data, no multi-tenant concerns.

## Core Workflow

The pipeline runs twice per week on a schedule (launchd on macOS, since the machine is a Mac and cron is deprecated there).

### Stage 1: Ingest
- Query Gmail for messages matching: from jobalerts-noreply@linkedin.com, newer_than:14d.
- Gmail access via the Gmail MCP server already configured for Claude, or the Gmail API with OAuth if running outside Claude Code.
- Parse the HTML body of each alert. Extract per job card: title, company, location, workplace type if shown, snippet text, and the LinkedIn URL (for reference only, not fetching).
- LinkedIn URLs in alert emails are tracking redirects. Store them as provenance but never treat them as a data source.

### Stage 2: Resolve and verify
For each extracted job, find the canonical posting in this order:
1. Company ATS API via existing scan scripts (scan-greenhouse.sh, scan-lever.sh, scan-ashby.sh, scan-workable.sh), matching on company slug plus fuzzy title match.
2. The free job APIs the plugin already supports (Remotive, The Muse, Jobicy, etc.).
3. Web search on title plus company plus location as last resort, using verify-url.sh on whatever is found.

Record for every job: canonical URL, source type (ats, api, web, unverified), and posted or updated date from the canonical source, not from the email.

Freshness rule: keep jobs whose canonical posted date is within 14 days. Jobs that resolve only to aggregators with no canonical date are marked unverified and ranked below verified jobs, never silently dropped (a real job should not vanish because verification failed, but it must be labeled).

### Stage 3: Dedup and history
- Run existing deduplicate-jobs.py across the batch.
- Maintain a SQLite ledger (consistent with the Briefing and Recall stack) of every job previously seen, keyed on normalized company plus title plus location. Repeat alerts for the same role must not resurface as new. The ledger also stores status: new, reported, applied, skipped, expired.

### Stage 4: Score
- Use the existing Phase 6 rubric unchanged: skills 30, seniority 20, sector 20, work mode 15, culture 10, recency 5. Tiers: 80 to 100 strong, 60 to 79 good, 40 to 59 growth.
- Career brief is the scoring reference. Source of truth lives in Google Drive; the pipeline reads a local synced copy (path in config). A stale-brief warning fires if the local copy is older than 60 days.
- Apply standing location rules:
  - Dubai or UAE roles: assume visa sponsorship unless the posting signals otherwise; do not penalize for missing visa language.
  - US remote roles: viable (US citizen); "must reside in US" plus remote counts as viable.
  - Singapore: acceptable, no penalty.
- Apply dealbreakers from the brief: rigid office mandates, requirements-factory cultures, IC-only roles without ownership, pure research without product mandate.
- Product-mandate guard (the keyword-bait check): when a role scores high mostly on methods keywords (foresight, workshops, storytelling, design thinking), check what the role produces and who owns the output. If outputs are reports feeding someone else's plan with no build or ship mandate, cap the score in the growth tier and flag the reason. This guard exists because methods vocabulary reliably over-attracts.

### Stage 5: Report
- Produce a Markdown report per run: Tier 1 and Tier 2 jobs with score breakdown, two-line rationale, canonical link, verification status, and posted date. Skipped and stale jobs go in a collapsed summary with one-line reasons.
- Deliver by saving to a reports folder and optionally emailing to self via the same Gmail account.
- No em dashes in any generated text.

### Stage 6: CV tailoring (Tier 1 only, human-gated)
Tailoring runs only for Tier 1 roles, and only produces drafts. Nothing is ever submitted automatically.

IDML pipeline, as validated manually:
1. Unzip the template IDML (master CV). Text lives in Stories/*.xml inside Content elements.
2. Edits are restricted to a whitelist of stories defined in config: profile paragraph, core strengths line, a small set of swappable experience bullets, the methods and tools line, and the page 3 letter story. Structure, geometry, spreads, and styles are never touched.
3. Length budget: every replacement stays within plus or minus 10 percent of the original character count to limit overset risk. The report must still tell the user to check for overset in InDesign, since the script cannot render frames.
4. Repackaging rules: mimetype is the first zip entry, stored uncompressed; no directory entries; all XML validated well-formed before output.
5. Content rules: never invent experience; every claim must trace to the master CV or career brief. British or American spelling follows the posting. No em dashes. Tone matches the master CV.
6. Output: one IDML per Tier 1 role, named CV-rabourn-{company}-{date}.idml, plus a plain text diff summary of exactly what changed and why, so review takes minutes.

## Inputs

1. Gmail access (MCP server or OAuth credentials).
2. Sender filter: jobalerts-noreply@linkedin.com (configurable list, since other alert senders may be added later).
3. Career brief: local synced copy of the Google Drive doc, path in config.
4. Master CV in IDML, supplied once at setup to a fixed path (for example ~/job-matcher/data/master-cv.idml). The story map is auto-generated from it by the helper. On each run the pipeline checks the file's modification time; if the CV has been replaced or edited, the story map regenerates automatically and the new map is flagged for a quick confirmation. Updating the CV is just saving over the file; no command needed.
5. Existing job-matcher data files: target-companies.local.json, sector-keywords.local.json.
6. SQLite ledger path.

## Outputs

1. Ranked Markdown report per run with rationale, canonical links, verification status, and freshness evidence.
2. Tailored IDML CV drafts for Tier 1 roles plus per-CV change summaries.
3. Updated ledger.
4. Run log: emails reviewed, jobs extracted, jobs verified, jobs deduped, jobs skipped and why.

## Key Requirements

1. Never fetch LinkedIn job URLs. The email is a lead source; the canonical source is the employer ATS or an open API.
2. Freshness is judged from the canonical source date, never from email metadata or aggregator claims.
3. Unverifiable jobs are labeled, not hidden and not trusted.
4. Stale, expired, duplicate, and dealbreaker roles are excluded from the main report with logged reasons.
5. Every recommended job carries a citation: where it was found and how it was verified.
6. Tailored CVs contain no invented experience and no em dashes, and preserve template structure exactly.
7. All CV output is draft-only and human-reviewed. The pipeline never applies to jobs.
8. The pipeline degrades gracefully: if Gmail is unreachable, ATS calls fail, or the brief is missing, the run reports the failure rather than producing a partial report that looks complete.

## Non-goals (v1)

1. Scraping LinkedIn itself.
2. Auto-submission of applications.
3. Cover letter generation (the page 3 letter story is replaced with a placeholder note in v1; tailored letters remain a manual or interactive step because they need judgment about positioning).
4. Mobile execution. The pipeline runs on the Mac; results can be reviewed from the phone via the emailed report or Claude Code remote control.
5. Sources beyond LinkedIn alert emails (the scanner interface should make adding Indeed or Google alert emails easy later).

## Open Questions

1. Should Tier 1 results trigger a push notification rather than waiting for the emailed report?
2. RESOLVED: Story map config is generated automatically. A helper unzips the IDML, extracts text previews per story, and Claude classifies each story into a role (profile, core strengths, experience, methods, letter, tagline, header) with sensible editable defaults. The user supplies only the career brief and a recent IDML CV; the helper presents the inferred map for a quick confirmation before first use, then the pipeline relies on it. Re-run the helper whenever the template changes.
3. Does the ledger eventually feed Recall, so job-search history becomes part of the personal memory system?
4. Threshold for CV generation: Tier 1 only, or Tier 1 plus the top Tier 2 role per run?

## Non-Goals

The first version does not need to apply for jobs automatically.

The first version does not need to log into LinkedIn.

The first version does not need to generate cover letters unless added later.

The first version does not need a full web dashboard.

## Technical Approach

Build as a Python script scheduled through cron, GitHub Actions, a local scheduler, or another lightweight automation service.

Use the Gmail API to retrieve matching job alert emails.

Use an LLM to parse emails, extract job details, compare jobs to the career brief, and generate tailored CV content.

Use web search where needed to locate the job posting outside LinkedIn.

Use an IDML parsing and generation process to modify the existing CV template and export a new IDML file.

## Acceptance Criteria

A successful run should:

1. Search Gmail for LinkedIn job alert emails from the target sender
2. Extract a clean list of potential job opportunities
3. Remove duplicates and stale postings
4. Confirm that shortlisted postings are recent
5. Rank jobs against the career brief
6. Produce a clear ranked list with fit rationale
7. Generate at least one tailored CV in IDML format using the example CV template
8. Avoid fabricating job details, dates, or user experience

## Open Questions

1. Where will the career brief file be stored?
2. Where will the IDML template be stored?
3. Should the script generate a CV for every strong match or only the top one to three jobs per run?
4. Should the system send a summary email after each run?
5. Should final CVs require manual approval before being saved or exported?
