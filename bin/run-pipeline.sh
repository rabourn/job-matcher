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

mkdir -p logs
LOG="logs/run-$(date +%Y%m%d-%H%M%S).log"

# Tools the pipeline is allowed to use unattended. Gmail tools are the
# claude.ai connector (validated to work headless). WebSearch is the
# last-resort resolver. Bash drives the scripts/ filters.
ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep,ToolSearch,WebSearch,WebFetch,mcp__claude_ai_Gmail__search_threads,mcp__claude_ai_Gmail__get_thread"

# Default to Opus for scheduled runs (decision 2026-06-12: CV drafting quality
# matters; revisit scoring on Sonnet if usage becomes a problem). Interactive
# sessions stay on the user's default model.
PIPELINE_MODEL="${PIPELINE_MODEL:-opus}"

PROMPT="Read skills/screen-alerts/SKILL.md in this repository and execute it exactly, start to finish. Work from the repo root. Do not ask questions."

{
  echo "=== screen-alerts run $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  ${CLAUDE_BIN:-claude} -p "$PROMPT" \
    --allowedTools "$ALLOWED_TOOLS" \
    --output-format text \
    ${PIPELINE_MODEL:+--model "$PIPELINE_MODEL"}
  status=$?
  echo "=== exit $status at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  exit $status
} >> "$LOG" 2>&1
