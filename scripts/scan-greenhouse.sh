#!/bin/bash
# Query Greenhouse ATS public API for a company's job board.
#
# Usage:
#   scan-greenhouse.sh SLUG [--content]
#
# Examples:
#   scan-greenhouse.sh planetlabs
#   scan-greenhouse.sh wikimedia --content
#
# Output: Raw JSON to stdout. Empty JSON object on error.

set -euo pipefail

SLUG="${1:-}"
CONTENT_FLAG=""

if [ -z "$SLUG" ]; then
  echo '{"error": "Usage: scan-greenhouse.sh SLUG [--content]"}' >&2
  echo '{"jobs": []}'
  exit 1
fi

# Check for --content flag
for arg in "$@"; do
  if [ "$arg" = "--content" ]; then
    CONTENT_FLAG="?content=true"
  fi
done

URL="https://boards-api.greenhouse.io/v1/boards/${SLUG}/jobs${CONTENT_FLAG}"

response=$(curl -s -w "\n%{http_code}" "$URL" 2>/dev/null) || {
  echo "Error fetching $URL" >&2
  echo '{"jobs": []}'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Greenhouse ${SLUG}: HTTP ${http_code}" >&2
  echo '{"jobs": []}'
  exit 0
fi

echo "$body"
