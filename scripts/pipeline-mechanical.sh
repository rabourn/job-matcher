#!/bin/bash
# Deterministic middle of the pipeline: dedup, ledger upsert, filter to new,
# resolve to canonical ATS/Workday with full descriptions.
#
# This runs as plain subprocesses so the long resolve step never sits inside
# an LLM turn. The headless agent twice backgrounded the resolver and ended
# its turn, leaving the batch unscored (2026-06-11, 2026-06-13). Slow but
# reliable in bash beats fast but abandoned in an agent.
#
# Usage:
#   scripts/pipeline-mechanical.sh INPUT_JOBS_JSON OUT_RESOLVED_JSON
#   scripts/pipeline-mechanical.sh --from-ledger OUT_RESOLVED_JSON
#
# INPUT_JOBS_JSON: parsed alert jobs (normal run, from the ingest phase).
# --from-ledger:   resolve the ledger's current 'new' rows instead (re-score
#                  runs, which skip Gmail because the roles are already known).
# Output: OUT_RESOLVED_JSON, the resolved jobs array (with descriptions),
# ready for the scoring phase.

set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MODE_LEDGER=0
if [ "${1:-}" = "--from-ledger" ]; then
  MODE_LEDGER=1
  OUT="${2:?usage: pipeline-mechanical.sh --from-ledger OUT}"
else
  INPUT="${1:?usage: pipeline-mechanical.sh INPUT OUT}"
  OUT="${2:?usage: pipeline-mechanical.sh INPUT OUT}"
fi

TMP="$(dirname "$OUT")"
mkdir -p "$TMP"

if [ "$MODE_LEDGER" -eq 1 ]; then
  # Export ledger 'new' rows into the resolver's input schema.
  python3 - "$TMP/new.json" <<'PY'
import sqlite3, json, sys, os
db = os.path.join('data', 'ledger.db')
conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT key,company,title,location,linkedin_url FROM jobs WHERE status='new'").fetchall()
jobs = [{"ledger_key": r["key"], "company": r["company"], "title": r["title"],
         "location": r["location"], "linkedin_url": r["linkedin_url"] or "",
         "source": "ledger", "description_text": "", "verification_status": "UNVERIFIED"}
        for r in rows]
json.dump(jobs, open(sys.argv[1], "w"))
print(f"exported {len(jobs)} ledger 'new' rows", file=sys.stderr)
PY
else
  # Normal path: dedup within batch, upsert to ledger, keep only new.
  python3 scripts/deduplicate-jobs.py < "$INPUT" > "$TMP/deduped.json"
  python3 scripts/ledger.py upsert < "$TMP/deduped.json" > "$TMP/upserted.json"
  python3 - "$TMP/upserted.json" "$TMP/new.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
new = [j for j in data if j.get("ledger_status") == "new"]
json.dump(new, open(sys.argv[2], "w"))
print(f"{len(new)} new of {len(data)} after ledger dedup", file=sys.stderr)
PY
  python3 scripts/ledger.py expire --days 60 2>/dev/null || true
fi

# The slow part: resolve to canonical ATS/Workday with full descriptions.
# Runs to completion here, in bash, where no agent can abandon it.
python3 scripts/resolve-job.py < "$TMP/new.json" > "$OUT"

COUNT=$(python3 -c "import json;print(len(json.load(open('$OUT'))))" 2>/dev/null || echo "?")
ATS=$(python3 -c "import json;print(sum(1 for j in json.load(open('$OUT')) if j.get('source_type')=='ats'))" 2>/dev/null || echo "?")
echo "mechanical pipeline done: $COUNT resolved, $ATS via ATS/Workday -> $OUT" >&2
