#!/bin/bash
# Query Remotive API for remote job listings.
#
# Usage:
#   search-remotive.sh [--category CAT] [--limit N]
#
# Categories: software-dev, design, product, marketing, customer-support,
#             sales, devops, finance, human-resources, qa, writing, all-others
#
# Note: Remotive has no keyword search — fetch all and filter locally.
# Output: Raw JSON to stdout.

set -euo pipefail

CATEGORY=""
LIMIT=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --category) CATEGORY="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    *) shift ;;
  esac
done

URL="https://remotive.com/api/remote-jobs"
PARAMS=""

if [ -n "$CATEGORY" ]; then
  PARAMS="?category=${CATEGORY}"
fi

if [ -n "$LIMIT" ]; then
  SEP="?"
  [ -n "$PARAMS" ] && SEP="&"
  PARAMS="${PARAMS}${SEP}limit=${LIMIT}"
fi

response=$(curl -s -w "\n%{http_code}" "${URL}${PARAMS}" 2>/dev/null) || {
  echo "Error fetching Remotive API" >&2
  echo '{"jobs": []}'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "Remotive: HTTP ${http_code}" >&2
  echo '{"jobs": []}'
  exit 0
fi

echo "$body"
