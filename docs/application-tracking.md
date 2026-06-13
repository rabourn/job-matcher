# Application lifecycle tracking (design)

Status: designed 2026-06-13, to implement after the in-flight re-eval run
frees the ledger. Decision: file-only surfacing (no daily-note section).

## Goal

Track roles Tanya has actually applied to and their outcomes by scanning
Gmail, maintaining a human-readable tracker in the vault. Independent of what
the screen-alerts pipeline surfaces: follows what she applied to, however
found.

## Source signals (validated against real inbox 2026-06-13)

- Acknowledgement: `notification@recruitment.etihad.ae` "Thank you for
  submitting your application for the position of Design Experience Manager
  at Etihad Airways."
- Rejection: `recruitment@tech.gov.sg` "we will not be proceeding with your
  candidacy for the Principal Designer - AI Workflows & Processes."
- Application sent: `jobs-noreply@linkedin.com` "your application was sent to
  GovTech Singapore" (LinkedIn Easy Apply; title often only in body).

## Design

New scan phase (own Gmail search, separate from the LinkedIn alert ingest):

1. Search Gmail for lifecycle signals over a lookback window:
   - acknowledgement: "thank you for applying", "application received",
     "we received your application", "thank you for submitting your application"
   - rejection: "not proceeding", "unfortunately", "not moving forward",
     "decided to move forward with other", "will not be progressing"
   - interview: "invite you to interview", "schedule a call", "next steps",
     "phone screen"
   - plus known ATS/recruiter senders (greenhouse, lever, workday, ashby,
     myworkday, smartrecruiters, tech.gov.sg, recruitment.* domains).
2. Parse company, title (from subject or body), signal type, date.
3. Update `~/cairn/projects/job-search/applications.md`:
   - new application -> "Awaiting response"
   - acknowledgement on an existing entry -> status acknowledged
   - interview -> "Interviewing" section
   - rejection/offer -> "Closed" with outcome and date
   - never overwrite a hand-entered note; merge, do not clobber.
4. Ledger sync (default ON): when an outcome matches a ledger row by
   normalized company AND title (same fuzzy rules as resolve-job.py), set
   that row's status (applied/rejected). Company-only matches do NOT update
   the ledger (the GovTech case: applied role != surfaced role).

## Guardrails

- Conservative matching; when company matches but title does not, record the
  application in applications.md but leave the ledger alone.
- Single-user, personal Gmail; the scan reads beyond LinkedIn alerts into the
  general inbox, which is expected and fine.
- No daily-note surfacing (Tanya's choice 2026-06-13). The file is the
  interface; Recall indexes it for `recall ask`.

## Open question for later

- Could feed the ledger's application history into Recall as a proper source
  (PRD open question 3) so "how many roles did I apply to in June" is
  answerable. Not in this iteration.
