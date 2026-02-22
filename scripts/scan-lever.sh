#!/bin/bash
# Query Lever ATS public API for a company's job postings.
#
# Usage:
#   scan-lever.sh SLUG
#
# Examples:
#   scan-lever.sh twilio
#
# Output: Raw JSON array to stdout. Empty array on error.

set -euo pipefail

SLUG="${1:-}"

if [ -z "$SLUG" ]; then
  echo '{"error": "Usage: scan-lever.sh SLUG"}' >&2
  echo '[]'
  exit 1
fi

URL="https://api.lever.co/v0/postings/${SLUG}"

response=$(curl -s -w "\n%{http_code}" "$URL" 2>/dev/null) || {
  echo "Error fetching $URL" >&2
  echo '[]'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Lever ${SLUG}: HTTP ${http_code}" >&2
  echo '[]'
  exit 0
fi

echo "$body"
