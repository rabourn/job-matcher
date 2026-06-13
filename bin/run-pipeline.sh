#!/bin/bash
# Headless runner for the screen-alerts pipeline. Invoked by launchd twice a
# week (see setup/com.rabourn.job-alerts.plist), or manually:
#
#   bin/run-pipeline.sh
#
# Runs claude -p with the screen-alerts skill. The skill never asks questions
# and reports failures into the run report rather than hanging.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

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
LOG="logs/run-${STAMP}.log"          # human-readable: final report text
TRACE="logs/run-${STAMP}.jsonl"      # full action trace: every tool call and result

# Tools the pipeline is allowed to use unattended. Gmail tools are the
# claude.ai connector (validated to work headless). WebSearch is the
# last-resort resolver. Bash drives the scripts/ filters.
ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep,ToolSearch,WebSearch,WebFetch,mcp__claude_ai_Gmail__search_threads,mcp__claude_ai_Gmail__get_thread"

# Default to Opus for scheduled runs (decision 2026-06-12: CV drafting quality
# matters; revisit scoring on Sonnet if usage becomes a problem). Interactive
# sessions stay on the user's default model.
PIPELINE_MODEL="${PIPELINE_MODEL:-opus}"

PROMPT="Read skills/screen-alerts/SKILL.md in this repository and execute it exactly, start to finish. Work from the repo root. Do not ask questions."

echo "=== screen-alerts run $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"

# stream-json --verbose emits every event (assistant turns, tool calls, tool
# results) as JSONL: the forensic record when a run does something
# non-obvious. The human-readable final text is extracted into $LOG after.
"$CLAUDE_BIN" -p "$PROMPT" \
  --allowedTools "$ALLOWED_TOOLS" \
  --output-format stream-json --verbose \
  ${PIPELINE_MODEL:+--model "$PIPELINE_MODEL"} \
  >> "$TRACE" 2>> "$LOG"
status=$?

# Pull the final result text (and session id for transcript lookup) into the
# readable log. jq -r over the result event; tolerate a missing one (crash).
if command -v jq >/dev/null; then
  jq -r 'select(.type == "result") | "session: \(.session_id // "unknown")\n\n\(.result // "(no result text)")"' "$TRACE" >> "$LOG" 2>/dev/null
fi
echo "=== exit $status at $(date -u +%Y-%m-%dT%H:%M:%SZ) | full trace: $TRACE ===" >> "$LOG"
exit $status
