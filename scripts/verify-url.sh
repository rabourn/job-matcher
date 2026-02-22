#!/bin/bash
# Verify whether a job listing URL is still live/active.
#
# Usage:
#   verify-url.sh URL
#
# Output: JSON with {url, status: VERIFIED|EXPIRED|UNVERIFIABLE, http_code, reason}
#
# Checks:
# 1. HTTP HEAD request — 404/410 = EXPIRED
# 2. HTTP GET + scan for "no longer available", "position filled", "closed" text
# 3. Redirect to generic careers page = likely EXPIRED

set -euo pipefail

URL="${1:-}"

if [ -z "$URL" ]; then
  echo '{"error": "Usage: verify-url.sh URL", "status": "UNVERIFIABLE"}'
  exit 1
fi

# Step 1: HTTP HEAD check
http_code=$(curl -s -o /dev/null -w "%{http_code}" \
  -L --max-redirs 5 \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  --connect-timeout 10 --max-time 15 \
  "$URL" 2>/dev/null) || http_code="000"

if [ "$http_code" = "404" ] || [ "$http_code" = "410" ]; then
  echo "{\"url\": \"$URL\", \"status\": \"EXPIRED\", \"http_code\": $http_code, \"reason\": \"HTTP $http_code response\"}"
  exit 0
fi

if [ "$http_code" = "000" ] || [ "$http_code" = "403" ]; then
  echo "{\"url\": \"$URL\", \"status\": \"UNVERIFIABLE\", \"http_code\": $http_code, \"reason\": \"Connection failed or access denied\"}"
  exit 0
fi

if [ "$http_code" != "200" ] && [ "$http_code" != "301" ] && [ "$http_code" != "302" ]; then
  echo "{\"url\": \"$URL\", \"status\": \"UNVERIFIABLE\", \"http_code\": $http_code, \"reason\": \"Unexpected HTTP status\"}"
  exit 0
fi

# Step 2: HTTP GET and scan page content for expired indicators
body=$(curl -s -L --max-redirs 5 \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  --connect-timeout 10 --max-time 20 \
  "$URL" 2>/dev/null) || body=""

if [ -z "$body" ]; then
  echo "{\"url\": \"$URL\", \"status\": \"UNVERIFIABLE\", \"http_code\": $http_code, \"reason\": \"Empty response body\"}"
  exit 0
fi

# Check for expired/closed indicators (case-insensitive)
body_lower=$(echo "$body" | tr '[:upper:]' '[:lower:]')

expired_phrases=(
  "no longer available"
  "no longer accepting"
  "position has been filled"
  "position filled"
  "this job has been closed"
  "this job is closed"
  "this role has been filled"
  "this posting has expired"
  "this listing has expired"
  "applications are closed"
  "applications are no longer being accepted"
  "this job has expired"
  "this opportunity is closed"
  "this position is no longer available"
  "job not found"
  "the position you are looking for is no longer"
  "this role is no longer open"
)

for phrase in "${expired_phrases[@]}"; do
  if echo "$body_lower" | grep -q "$phrase"; then
    echo "{\"url\": \"$URL\", \"status\": \"EXPIRED\", \"http_code\": $http_code, \"reason\": \"Page contains: $phrase\"}"
    exit 0
  fi
done

# Step 3: Check if redirected to a generic careers page (heuristic)
# If the final URL looks very different from the input URL and is a generic /careers page
final_url=$(curl -s -o /dev/null -w "%{url_effective}" -L --max-redirs 5 \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  --connect-timeout 10 --max-time 15 \
  "$URL" 2>/dev/null) || final_url=""

if [ -n "$final_url" ] && [ "$final_url" != "$URL" ]; then
  # If redirected to a generic careers page
  if echo "$final_url" | grep -qE '/careers/?$|/jobs/?$|/openings/?$'; then
    echo "{\"url\": \"$URL\", \"status\": \"EXPIRED\", \"http_code\": $http_code, \"reason\": \"Redirected to generic careers page: $final_url\"}"
    exit 0
  fi
fi

# If we got here with a 200 and no expired indicators, it's likely live
echo "{\"url\": \"$URL\", \"status\": \"VERIFIED\", \"http_code\": $http_code, \"reason\": \"Page loads with no expired indicators\"}"
