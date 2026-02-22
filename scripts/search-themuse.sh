#!/bin/bash
# Query The Muse API for job listings.
#
# Usage:
#   search-themuse.sh [--level LEVEL] [--category CAT] [--location LOC] [--page PAGE] [--pages N]
#
# Levels: "Entry Level", "Mid Level", "Senior Level", "Management"
# Categories: "Product Management", "Design and UX", "Data Science", "Engineering"
# Location: "Flexible / Remote", "New York, NY", "San Francisco, CA", etc.
#
# The Muse has the best server-side filtering of the free APIs.
# Free tier: 500 requests/hour.
#
# --pages N fetches N pages (0 through N-1) and merges all results into one response.
# Output: Raw JSON to stdout.

set -euo pipefail

LEVEL=""
CATEGORY=""
LOCATION=""
PAGE="0"
PAGES="1"

while [[ $# -gt 0 ]]; do
  case $1 in
    --level) LEVEL="$2"; shift 2 ;;
    --category) CATEGORY="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --page) PAGE="$2"; shift 2 ;;
    --pages) PAGES="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Build base URL with query parameters (without page)
BASE_URL="https://www.themuse.com/api/public/jobs?"
PARAMS=""

if [ -n "$LEVEL" ]; then
  ENCODED_LEVEL=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$LEVEL'))")
  PARAMS="${PARAMS}&level=${ENCODED_LEVEL}"
fi

if [ -n "$CATEGORY" ]; then
  ENCODED_CAT=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$CATEGORY'))")
  PARAMS="${PARAMS}&category=${ENCODED_CAT}"
fi

if [ -n "$LOCATION" ]; then
  ENCODED_LOC=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$LOCATION'))")
  PARAMS="${PARAMS}&location=${ENCODED_LOC}"
fi

# Single page mode (original behaviour)
if [ "$PAGES" = "1" ]; then
  URL="${BASE_URL}page=${PAGE}${PARAMS}"
  response=$(curl -s -w "\n%{http_code}" "$URL" 2>/dev/null) || {
    echo "Error fetching The Muse API" >&2
    echo '{"results": []}'
    exit 0
  }

  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [ "$http_code" != "200" ]; then
    echo "The Muse: HTTP ${http_code}" >&2
    echo '{"results": []}'
    exit 0
  fi

  echo "$body"
  exit 0
fi

# Multi-page mode: fetch pages 0 through PAGES-1 and merge results
TMPDIR_MUSE=$(mktemp -d)
trap "rm -rf $TMPDIR_MUSE" EXIT

echo '[]' > "$TMPDIR_MUSE/all_results.json"

for ((p=0; p<PAGES; p++)); do
  URL="${BASE_URL}page=${p}${PARAMS}"
  response=$(curl -s -w "\n%{http_code}" "$URL" 2>/dev/null) || continue

  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [ "$http_code" != "200" ]; then
    echo "The Muse page ${p}: HTTP ${http_code}" >&2
    continue
  fi

  # Merge this page's results into the accumulator
  python3 -c "
import json, sys

with open('$TMPDIR_MUSE/all_results.json') as f:
    existing = json.load(f)

page_data = json.load(sys.stdin)
results = page_data.get('results', [])
page_count = page_data.get('page_count', 0)

existing.extend(results)

with open('$TMPDIR_MUSE/all_results.json', 'w') as f:
    json.dump(existing, f)

print(f'The Muse: fetched page {$p}/{page_count} ({len(results)} results)', file=sys.stderr)

# Write page_count for the outer loop to check
with open('$TMPDIR_MUSE/page_count.txt', 'w') as f:
    f.write(str(page_count))
" <<< "$body" 2>&2 || continue

  # Stop if we've reached the last page
  if [ -f "$TMPDIR_MUSE/page_count.txt" ]; then
    page_count=$(cat "$TMPDIR_MUSE/page_count.txt")
    if [ "$p" -ge "$((page_count - 1))" ]; then
      break
    fi
  fi

  # Brief pause to respect rate limits
  sleep 0.2
done

# Output merged results in the same format as single-page
python3 -c "
import json
with open('$TMPDIR_MUSE/all_results.json') as f:
    results = json.load(f)
print(json.dumps({'results': results, 'page_count': 0, 'total': len(results)}))
"
