#!/bin/bash
# Query Jobicy API for remote job listings.
#
# Usage:
#   search-jobicy.sh [--count N] [--tag TAG] [--geo GEO]
#
# Tags: e.g., "product-management", "ux-design", "marketing"
# Geo: e.g., "usa", "europe", "uk", "anywhere"
#
# Jobicy includes salary data, making it valuable for compensation estimates.
# Output: Raw JSON to stdout.

set -euo pipefail

COUNT="50"
TAG=""
GEO=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --count) COUNT="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --geo) GEO="$2"; shift 2 ;;
    *) shift ;;
  esac
done

URL="https://jobicy.com/api/v2/remote-jobs?count=${COUNT}"

if [ -n "$TAG" ]; then
  URL="${URL}&tag=${TAG}"
fi

if [ -n "$GEO" ]; then
  URL="${URL}&geo=${GEO}"
fi

response=$(curl -s -w "\n%{http_code}" "$URL" 2>/dev/null) || {
  echo "Error fetching Jobicy API" >&2
  echo '{"jobs": []}'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Jobicy: HTTP ${http_code}" >&2
  echo '{"jobs": []}'
  exit 0
fi

echo "$body"
