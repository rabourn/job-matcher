#!/bin/bash
# Scan Gmail for application-lifecycle emails and update the vault tracker.
#
#   bin/scan-applications.sh [DAYS]   (default 30)
#
# Two phases, same principle as the main pipeline: the model does the fuzzy
# extraction (deciding which emails are genuine applications and pulling out
# company/title/outcome), and the deterministic script merges the records and
# syncs the ledger. Lightweight: one Gmail pass, no long mechanical step.

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

DAYS="${1:-30}"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
for cand in "$HOME/.local/bin/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
  [ -n "$CLAUDE_BIN" ] && break
  [ -x "$cand" ] && CLAUDE_BIN="$cand"
done
[ -z "$CLAUDE_BIN" ] && { echo "FATAL: claude not found" >&2; exit 127; }

mkdir -p logs
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="data/.applications-${STAMP}.json"

PROMPT="Search Gmail for job-application lifecycle emails from the last ${DAYS} days: application acknowledgements ('thank you for applying', 'we received your application', 'your application was sent'), rejections ('not proceeding', 'regret to inform', 'unfortunately we'), and interview invitations (Teams/Zoom invites tied to a role, 'invite you to interview', 'next steps'). Be CONSERVATIVE: include only genuine emails about Tanya's own job applications. EXCLUDE newsletters, job-board digests (LinkedIn alerts, design-gigs mailing lists), recruiter prospecting/spam (GulfTalent etc.), conference CFPs, and marketing.

For each genuine email, extract one record: {company, title, status (applied|acknowledged|interviewing|rejected|offer|withdrawn), date (YYYY-MM-DD), source (short, e.g. sender domain or 'LinkedIn'), note (optional)}. If a title is not stated, use 'role unconfirmed' and add a note. Write a JSON array of records to ${OUT} and nothing else. Run synchronously; do not background."

"$CLAUDE_BIN" -p "$PROMPT" \
  --allowedTools "Bash,Read,Write,ToolSearch,mcp__claude_ai_Gmail__search_threads,mcp__claude_ai_Gmail__get_thread" \
  --output-format text \
  ${PIPELINE_MODEL:+--model "$PIPELINE_MODEL"} \
  >> "logs/scan-applications-${STAMP}.log" 2>&1

if [ -s "$OUT" ]; then
  python3 scripts/update-applications.py < "$OUT" 2>> "logs/scan-applications-${STAMP}.log"
  echo "applications scan done; records: $OUT"
else
  echo "applications scan: no records extracted (see logs/scan-applications-${STAMP}.log)" >&2
fi
