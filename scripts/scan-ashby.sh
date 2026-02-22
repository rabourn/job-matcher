#!/bin/bash
# Query Ashby posting API for a company's job board.
#
# Usage:
#   scan-ashby.sh SLUG
#
# Examples:
#   scan-ashby.sh notion
#   scan-ashby.sh watershed
#
# Output: Raw JSON to stdout. Empty JSON object on error.

set -euo pipefail

SLUG="${1:-}"

if [ -z "$SLUG" ]; then
  echo '{"error": "Usage: scan-ashby.sh SLUG"}' >&2
  echo '{"jobs": []}'
  exit 1
fi

URL="https://api.ashbyhq.com/posting-api/job-board/${SLUG}"

response=$(curl -s -w "\n%{http_code}" "$URL" 2>/dev/null) || {
  echo "Error fetching $URL" >&2
  echo '{"jobs": []}'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Ashby ${SLUG}: HTTP ${http_code}" >&2
  echo '{"jobs": []}'
  exit 0
fi

echo "$body"
