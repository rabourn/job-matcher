#!/bin/bash
# Headless runner for the screen-alerts pipeline. Invoked by launchd twice a
# week (see setup/com.rabourn.job-alerts.plist), or manually:
#
#   bin/run-pipeline.sh                 # normal run (Gmail ingest + resolve + score)
#   bin/run-pipeline.sh --rescore       # re-score existing ledger 'new' rows (no Gmail)
#
# Three phases. The LLM is used only where judgment is required (Gmail ingest,
# scoring). The slow mechanical resolve runs as plain bash in between, because
# the agent twice backgrounded it and ended its turn, leaving the batch
# unscored (2026-06-11, 2026-06-13). Deterministic code for mechanical work;
# the model only for judgment.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MODE="normal"
[ "${1:-}" = "--rescore" ] && MODE="rescore"

# launchd runs with a minimal PATH that excludes ~/.local/bin (where claude
# is installed) and Homebrew. Resolve the claude binary explicitly so a
# scheduled run never dies with "command not found" (happened 2026-06-13).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
for cand in "$HOME/.local/bin/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
  [ -n "$CLAUDE_BIN" ] && break
  [ -x "$cand" ] && CLAUDE_BIN="$cand"
done
if [ -z "$CLAUDE_BIN" ]; then
  echo "FATAL: claude binary not found on PATH or known locations" >&2
  exit 127
fi

mkdir -p logs
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="logs/run-${STAMP}.log"
TRACE_INGEST="logs/run-${STAMP}-ingest.jsonl"
TRACE_SCORE="logs/run-${STAMP}-score.jsonl"
TMP="data/.pipeline-${STAMP}"
mkdir -p "$TMP"

PIPELINE_MODEL="${PIPELINE_MODEL:-opus}"

log() { echo "$@" >> "$LOG"; }
log "=== screen-alerts run $(date -u +%Y-%m-%dT%H:%M:%SZ) (mode: $MODE) ==="

# Run an agent phase: $1 = label, $2 = trace file, $3 = allowed tools, $4 = prompt.
run_agent() {
  local label="$1" trace="$2" tools="$3" prompt="$4"
  log "--- phase: $label ($(date -u +%H:%M:%SZ)) ---"
  "$CLAUDE_BIN" -p "$prompt" \
    --allowedTools "$tools" \
    --output-format stream-json --verbose \
    ${PIPELINE_MODEL:+--model "$PIPELINE_MODEL"} \
    >> "$trace" 2>> "$LOG"
  local st=$?
  if command -v jq >/dev/null; then
    jq -r 'select(.type=="result") | "session: \(.session_id // "?")\n\(.result // "(no result)")"' "$trace" >> "$LOG" 2>/dev/null
  fi
  return $st
}

GMAIL_TOOLS="Bash,Read,Write,Glob,Grep,ToolSearch,mcp__claude_ai_Gmail__search_threads,mcp__claude_ai_Gmail__get_thread"
SCORE_TOOLS="Bash,Read,Write,Edit,Glob,Grep,ToolSearch,WebSearch,WebFetch"

# ── Phase A: ingest (LLM, only for Gmail) ────────────────────────────────────
if [ "$MODE" = "normal" ]; then
  INGEST_PROMPT="Execute ONLY the Gmail ingest portion of skills/screen-alerts/SKILL.md (Phase 0 config and Phase 1 ingest). Read data/pipeline.local.json, then for each configured sender search Gmail and parse every alert email with scripts/parse-alert-email.py. Write the combined parsed-jobs array to ${TMP}/parsed.json. Do NOT dedup, resolve, or score. Stop immediately after writing ${TMP}/parsed.json. Do not background any command."
  run_agent "ingest" "$TRACE_INGEST" "$GMAIL_TOOLS" "$INGEST_PROMPT" || log "ingest phase exit nonzero"
fi

# ── Phase B: mechanical resolve (deterministic bash, never the agent) ─────────
log "--- phase: mechanical-resolve ($(date -u +%H:%M:%SZ)) ---"
if [ "$MODE" = "rescore" ]; then
  scripts/pipeline-mechanical.sh --from-ledger "${TMP}/resolved.json" >> "$LOG" 2>&1
else
  if [ ! -s "${TMP}/parsed.json" ]; then
    log "FATAL: ingest produced no ${TMP}/parsed.json; aborting before resolve"
    echo "=== exit 1 at $(date -u +%H:%M:%SZ): ingest produced nothing ===" >> "$LOG"
    exit 1
  fi
  scripts/pipeline-mechanical.sh "${TMP}/parsed.json" "${TMP}/resolved.json" >> "$LOG" 2>&1
fi
resolve_status=$?
if [ "$resolve_status" -ne 0 ] || [ ! -s "${TMP}/resolved.json" ]; then
  log "FATAL: mechanical resolve failed (status $resolve_status)"
  echo "=== exit 1 at $(date -u +%H:%M:%SZ): resolve failed ===" >> "$LOG"
  exit 1
fi

# ── Phase C: score, report, CV (LLM, only for judgment) ──────────────────────
SCORE_PROMPT="Resolution is COMPLETE. Read the resolved jobs at ${TMP}/resolved.json (each carries description_text from the canonical ad, or thin_description:true if the full ad could not be fetched). Also process any PDFs directly in data/job-ads/ (not the processed/ subfolder) as manual evidence per skill Phase 3 step 4: read each, score it, add it to the ledger and report, then move it into data/job-ads/processed/. Then execute Phase 4 onward of skills/screen-alerts/SKILL.md: score each job against the career brief and private overrides using the FULL description, apply every rule (overrides, dealbreakers, citizenship eligibility, location rules, product-mandate guard, freshness, unverified penalty), update the ledger with scores and statuses, write the run report, refresh the vault apply queue, and generate IDML CV drafts for Tier 1. Do NOT re-ingest from Gmail and do NOT re-resolve; the resolved file is authoritative. Do not background any command; run everything synchronously and finish all phases before ending."
run_agent "score" "$TRACE_SCORE" "$SCORE_TOOLS" "$SCORE_PROMPT"
score_status=$?

echo "=== exit $score_status at $(date -u +%Y-%m-%dT%H:%M:%SZ) | traces: $TRACE_INGEST $TRACE_SCORE | tmp: $TMP ===" >> "$LOG"
exit $score_status
