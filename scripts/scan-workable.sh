#!/bin/bash
# Query Workable widget API for a company's job listings.
#
# Usage:
#   scan-workable.sh SLUG
#
# Examples:
#   scan-workable.sh deliveryhero
#
# The Workable widget API uses POST with a JSON body.
# Output: Raw JSON to stdout. Empty JSON object on error.

set -euo pipefail

SLUG="${1:-}"

if [ -z "$SLUG" ]; then
  echo '{"error": "Usage: scan-workable.sh SLUG"}' >&2
  echo '{"jobs": []}'
  exit 1
fi

URL="https://apply.workable.com/api/v1/widget/accounts/${SLUG}"

response=$(curl -s -w "\n%{http_code}" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{}' \
  "$URL" 2>/dev/null) || {
  echo "Error fetching $URL" >&2
  echo '{"jobs": []}'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Workable ${SLUG}: HTTP ${http_code}" >&2
  echo '{"jobs": []}'
  exit 0
fi

echo "$body"
