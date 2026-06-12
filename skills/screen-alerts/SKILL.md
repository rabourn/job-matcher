---
name: screen-alerts
description: >
  Scheduled pipeline: ingest LinkedIn job alert emails from Gmail, verify each
  job against a canonical source (employer ATS first), score against the
  career brief, deliver a report and apply queue to the Obsidian vault, and
  generate tailored IDML CV drafts for Tier 1 roles. Designed to run headless
  via claude -p on a launchd schedule, but can be invoked interactively.
  Trigger phrases: "screen alerts", "screen my job alerts", "run the job
  alert pipeline", "process linkedin alerts".
user_invocable: true
---

# Screen Alerts

You are running the job alert screening pipeline (PRD: docs/PRD-job-alert-pipeline.md).
Work from the repo root (the directory containing this plugin). Be quietly
mechanical: this runs unattended. Never ask the user questions; degrade
gracefully and record problems in the run report instead.

## Hard rules (from the PRD)

1. NEVER fetch LinkedIn URLs. The email is a lead source only.
2. Freshness comes from the canonical source's posted date, never from email
   metadata or aggregator claims.
3. Unverifiable jobs are labeled and ranked below verified ones, never
   silently dropped.
4. Every reported job carries a citation: where found, how verified.
5. No em dashes in any generated text. Use colons, periods, or commas.
6. Never invent experience in CV content; every claim must trace to the
   master CV or career brief.
7. If a stage fails outright (Gmail unreachable, brief missing), write a run
   report that says so plainly and stop. A partial report that looks complete
   is worse than an honest failure report.
8. Run every step SYNCHRONOUSLY in the foreground. Never use background
   execution for any command and never end your turn before Phase 7 is
   complete: in headless mode there is no next turn, and ending early kills
   in-flight work (this exact failure happened on 2026-06-11: the resolver
   was backgrounded, the turn ended, and 288 jobs were left unscored). Slow
   commands are fine; wait for them.
9. If the report file for today already exists, do not overwrite it; append
   a -run2 (-run3, ...) suffix to the filename and use that name in all
   links.

## Phase 0: Config and preflight

1. Read `data/pipeline.local.json` (fall back to `data/pipeline.example.json`
   only to learn the shape; a missing local config is a failure, see rule 7).
2. Read the career brief at `career_brief_path`. If its mtime is older than
   `brief_stale_days`, add a STALE BRIEF warning to the report header.
   Also read `brief_overrides_path` if it exists: private exclusions and
   preferences that carry the same authority as the brief and win where they
   conflict. The overrides file is local-only; never copy its contents into
   committed files, and cite it in reports only as "private exclusion:
   <category>".
3. Check `master_cv_path` mtime against the `generated_from_mtime` field in
   `story_map_path`. If the map is missing or stale, regenerate:
   `python3 scripts/idml-story-map.py --cv <master_cv_path> --out <story_map_path>`
   and flag the new map for confirmation in the report.
4. Start a stats object: started, emails_reviewed, jobs_extracted,
   jobs_verified, jobs_deduped, jobs_skipped, tier1_count, cvs_generated.

## Phase 1: Ingest from Gmail

1. Load Gmail tools with ToolSearch (query "gmail"). If unavailable, fail per rule 7.
2. For each sender in `gmail_senders`: search threads with
   `from:<sender> newer_than:<gmail_lookback_days>d`, paging until exhausted
   (pageSize 50).
3. For each thread, get_thread with FULL_CONTENT. Results usually exceed the
   inline limit and are saved to a file; either way, extract
   `.messages[].plaintextBody` with jq into a temp file and run:
   `python3 scripts/parse-alert-email.py --text < body.txt`
   Collect all parsed jobs into one array. Count emails_reviewed and
   jobs_extracted.

## Phase 2: Ledger dedup

1. Within-batch dedup: `python3 scripts/deduplicate-jobs.py`.
2. Ledger: `python3 scripts/ledger.py upsert` (reads/writes the job array).
3. Keep only jobs with `ledger_status == "new"`. Jobs previously seen are not
   re-reported; count them as deduped.
4. `python3 scripts/ledger.py expire --days <ledger_expire_days>` to age out
   stale rows.

## Phase 3: Resolve to canonical source

1. `python3 scripts/resolve-job.py` annotates each job with source_type
   "ats" (canonical URL + real posted date) or "unverified".
2. For each still-unverified job, try the free APIs with company or title
   keywords: `scripts/search-remotive.sh`, `search-themuse.sh`,
   `search-jobicy.sh`, `search-himalayas.sh`, `search-remoteok.sh`, piping
   through `normalize-jobs.py --source <api>`. Fuzzy-match titles (same
   spirit as resolve-job.py). On a match: source_type "api", take the API's
   URL and posted date, verification_status API_ACTIVE.
3. Last resort, only for roles that would plausibly score Tier 1 or 2: one
   WebSearch per job for `"<title>" "<company>" careers OR jobs`, looking for
   the employer's own careers page or ATS posting. If found, run
   `scripts/verify-url.sh <url>`: VERIFIED -> source_type "web";
   EXPIRED -> mark skipped with reason; otherwise source_type stays
   "unverified".
4. Manual evidence folder: read any PDFs in `data/job-ads/` not yet prefixed
   `.processed-`. For each, extract company, title, work mode, posted date,
   and description from the ad, then match to a ledger row (same fuzzy
   company+title spirit as resolve-job.py; check both this batch and
   existing rows via `ledger.py check`). On a match: treat the ad as the
   job's full text for scoring, set source_type "manual",
   verification_status MANUAL_EVIDENCE, and use any posted date from the ad
   for freshness. The user supplied the ad deliberately, so a manual-
   evidence job skips the unverified penalty, but it is still labeled
   "manual evidence (user-supplied ad)" in the report with the citation.
   If a PDF matches no known job, score it as a new lead anyway and note
   where it came from. After processing, rename the file with a
   `.processed-` prefix.
5. Freshness rule: jobs whose canonical posted_date is older than
   `freshness_days` are skipped with reason "stale (posted <date>)".
   Jobs with no canonical date stay unverified: labeled, ranked below
   verified jobs, never dropped. Manual-evidence jobs without a date in
   the ad count as fresh: the user just printed them.

## Phase 4: Score against the career brief

Use the Phase 6 rubric from the match-jobs skill, unchanged:
skills 0-30, seniority 0-20, sector 0-20, work mode 0-15, culture/values
0-10, recency 0-5. Tiers: 80-100 Tier 1 (strong), 60-79 Tier 2 (good),
40-59 Tier 3 (growth).

Apply, in this order:

1. **Private overrides first**: exclusions from `brief_overrides_path` are
   dealbreakers; quiet preferences adjust scores. In reports, cite only
   "private exclusion: <category>".
2. **Dealbreakers from the brief** (score 0, skipped with reason): rigid
   office mandates (5 days in office, mandatory relocation), requirements
   factory cultures, IC-only roles without ownership, innovation theater,
   pure research without product mandate, sales/quota roles, deep
   engineering build roles, PMO/reporting roles.
3. **Standing location rules**:
   - Dubai/UAE roles: assume visa sponsorship unless the posting says
     otherwise; do not penalize missing visa language.
   - US remote roles: viable (US citizen). "Must reside in US" plus remote
     is viable.
   - Singapore: acceptable, no penalty.
4. **Product-mandate guard** (the keyword-bait check): if a role scores high
   mostly on methods keywords (foresight, workshops, storytelling, design
   thinking, HCD), check what the role produces and who owns the output. If
   outputs are reports feeding someone else's plan, with no build or ship
   mandate, cap the score at 59 (Tier 3) and record the reason. Methods
   vocabulary reliably over-attracts; this guard exists because of it.
5. **Unverified penalty**: unverified jobs get recency 0 and are listed in a
   separate, clearly labeled section, after verified jobs, regardless of score.

For every scored job, update the ledger:
`python3 scripts/ledger.py set-status --key <ledger_key> --status reported --score N --tier N --canonical-url URL --source-type TYPE --posted-date DATE`
(or `--status skipped --note "<reason>"` for dealbreakers/stale).

## Phase 5: Report and vault delivery

1. Write the run report to `<reports_dir>/YYYY-MM-DD-job-screen.md` and copy
   it to `<vault_reports_dir>/` (create directories as needed).
2. Report structure:
   - Header: date, stats line, any warnings (stale brief, new story map,
     failed sources).
   - Tier 1 and Tier 2 sections: for each job, score breakdown by dimension,
     a two line rationale, canonical link, verification status, source
     citation, posted date.
   - Unverified section (if any): same format, clearly labeled "could not
     verify against a canonical source".
   - Collapsed summary (details/summary block) of skipped jobs with one line
     reasons: stale, dealbreaker, duplicate, expired.
3. Update `<vault_apply_queue>`: regenerate the file from
   `python3 scripts/ledger.py queue --status reported --tier 1`. One section
   per pending role: title, company, score, canonical link, report link,
   CV draft path (once generated), and a checkbox line
   `- [ ] applied / - [ ] skipped`. Keep frontmatter
   `type: apply-queue` so Recall indexes it cleanly. When the user marks a
   role applied or skipped in conversation, reflect it with
   `ledger.py set-status` and regenerate the queue.
4. Vault writes are additive only: never modify other files in the vault.

## Phase 6: CV drafts for Tier 1 (human-gated)

Only for tiers in `cv_tiers` (default: Tier 1 only). Drafts only; never
submit anything.

1. Read the story map (`story_map_path`) and the master CV. Editable stories
   and their roles come from the map; never touch stories outside the
   whitelist.
2. For each Tier 1 role, draft replacement text for: profile paragraph, core
   strengths line, swappable experience bullets, methods and tools line. The
   page 3 letter story gets the v1 placeholder note, not a tailored letter.
   Content rules: every claim traces to the master CV or career brief;
   British or American spelling follows the posting; tone matches the master
   CV; no em dashes; each replacement within ±`cv_length_budget_pct`% of the
   original character count.
3. Apply: `python3 scripts/idml-apply.py --cv <master_cv_path> --map <story_map_path> --edits <edits.json> --out <cv_drafts_dir>/CV-rabourn-<company-slug>-<YYYY-MM-DD>.idml`
   The script enforces the whitelist, length budget, XML well-formedness,
   and IDML packaging rules; treat its failure as a per-job failure, note it
   in the report, and continue with other jobs.
4. Write a plain text diff summary next to each draft (same name, .changes.txt):
   what changed, why, and a reminder to check for overset text in InDesign.
5. Update the ledger with `--cv-path` and add the draft to the apply queue
   entry.

## Phase 7: Run log

1. Finish the stats object (finished, outcome "ok" or "failed: <reason>") and
   record it: `python3 scripts/ledger.py log-run` (JSON on stdin).
2. Append one line to `logs/pipeline.log`:
   `<ISO date> | emails N | extracted N | new N | verified N | tier1 N | cvs N | <outcome>`.
