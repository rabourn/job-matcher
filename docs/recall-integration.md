# Recall integration: apply queue in the daily note

Status: pipeline side implemented; Recall side designed, not yet implemented
(small change in the recall repo, to be reviewed before landing).

## How delivery works

The screen-alerts pipeline writes two things into the Obsidian vault
(`~/cairn`), which Recall's hourly sync indexes automatically:

1. Run reports: `career/reports/YYYY-MM-DD-job-screen.md`
2. The apply queue: `career/apply-queue.md`, regenerated from
   the ledger each run

Because both are ordinary vault files, `recall ask "what jobs should I apply
for?"` works with no Recall changes. The one Recall change below makes the
daily note actively surface the queue, which is the point: the daily note
tells you to apply.

## Apply queue file format (contract between the two repos)

```markdown
---
type: apply-queue
updated: 2026-06-15
---

# Apply queue

## Head of Product, Climate Platform: Verdant Analytics
- score: 84 (Tier 1)
- posted: 2026-06-12 (greenhouse, GUARANTEED open)
- apply: https://boards.greenhouse.io/verdant/jobs/123
- report: [[2026-06-15-job-screen]]
- cv draft: data/cv-drafts/CV-rabourn-verdant-analytics-2026-06-15.idml
- [ ] applied
- [ ] skipped
```

One `##` section per pending role. A role is **pending** while neither
checkbox is ticked. The pipeline regenerates this file from
`scripts/ledger.py queue --status reported --tier 1` on every run; roles
marked applied/skipped (in the ledger) drop out of the file. Ticking a
checkbox by hand in Obsidian is allowed; the next interactive session
reconciles ticks into the ledger via `ledger.py set-status`, and the
pipeline treats the ledger as truth.

## Recall-side change (to implement in recall repo)

In `recall/commands/generate_cmd.py`, add a deterministic section to the
daily note, same pattern as "Today's schedule":

1. New helper `_render_apply_queue_block(vault)`:
   - Read `vault / "career/apply-queue.md"`. Missing file or
     parse trouble: return `None` (section omitted, never an error).
   - A role is pending if its section has no ticked checkbox
     (`- [x]`). For each pending role, emit one line:
     `- Apply: {section heading} ({score line, abbreviated})`.
   - Return `None` when there are no pending roles, so quiet weeks add no
     noise to the note.
2. In the daily note template, insert after "Today's schedule":

   ```
   ## Applications to send
   {apply_block}
   ```

   Only when `_render_apply_queue_block` returned content.
3. The focus prompt (`_generate_focus`) may optionally receive a one line
   summary ("3 job applications pending, top: Verdant Analytics, score 84")
   so the suggested focus can mention it. Keep the listing itself
   deterministic, like the schedule block; the LLM never formats the queue.

Estimated size: one helper (~30 lines) plus two call sites. No DB or schema
changes. The parser must not assume more about the file than: `##` headings
per role, `- [ ] applied` / `- [ ] skipped` checkbox lines, `- score:` line.

## Future (PRD open question 3, resolved yes)

The ledger's full history (applied, skipped, expired, with dates and notes)
could later sync into recall.db as a proper source (`sources/jobsearch.py`
reading data/ledger.db), making questions like "how many roles did I apply
to in June?" answerable. Not in v1.
