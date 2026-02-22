#!/bin/bash
# Query Himalayas API for remote job listings.
#
# Usage:
#   search-himalayas.sh [--limit N]
#
# Note: Himalayas search endpoint is unreliable (returns all results regardless
# of query). Best approach is to fetch recent listings and filter locally.
# Output: Raw JSON to stdout.

set -euo pipefail

LIMIT="200"

while [[ $# -gt 0 ]]; do
  case $1 in
    --limit) LIMIT="$2"; shift 2 ;;
    *) shift ;;
  esac
done

URL="https://himalayas.app/jobs/api?limit=${LIMIT}"

response=$(curl -s -w "\n%{http_code}" "$URL" 2>/dev/null) || {
  echo "Error fetching Himalayas API" >&2
  echo '{"jobs": []}'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Himalayas: HTTP ${http_code}" >&2
  echo '{"jobs": []}'
  exit 0
fi

echo "$body"
