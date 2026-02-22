#!/bin/bash
# Query RemoteOK API for remote job listings.
#
# Usage:
#   search-remoteok.sh [--tag TAG]
#
# Tags: e.g., "design", "product", "dev", "finance"
#
# Note: Element [0] in the response is metadata — downstream normalizer skips it.
# Output: Raw JSON array to stdout.

set -euo pipefail

TAG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --tag) TAG="$2"; shift 2 ;;
    *) shift ;;
  esac
done

URL="https://remoteok.com/api"

if [ -n "$TAG" ]; then
  URL="${URL}?tag=${TAG}"
fi

# RemoteOK requires a User-Agent header
response=$(curl -s -w "\n%{http_code}" \
  -H "User-Agent: JobMatcher/2.0 (job search tool)" \
  "$URL" 2>/dev/null) || {
  echo "Error fetching RemoteOK API" >&2
  echo '[]'
  exit 0
}

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "RemoteOK: HTTP ${http_code}" >&2
  echo '[]'
  exit 0
fi

echo "$body"
