#!/bin/bash
# Query Workday's public CXS API for a company's job board.
#
# Usage:
#   scan-workday.sh TENANT [SEARCHTEXT] [SITE] [WD]
#
# Examples:
#   scan-workday.sh zillow "Director Experience Design"
#   scan-workday.sh mastercard "Product Design" CorporateCareers wd1
#
# Without SITE/WD, probes common cluster (wd5, wd1, wd3, wd2) and site-name
# combinations until one answers with JSON. Pass SITE and WD to skip
# discovery (the resolver caches and passes them after the first hit).
#
# Output: JSON {"total": N, "jobs": [...], "tenant", "site", "wd"} where each
# job carries an absolute externalUrl. Empty {"total": 0, "jobs": []} when no
# board is found. The endpoint is /wday/cxs/ (not /wd/cxs/, which returns
# "Requested page not found" as of 2026-06).

set -uo pipefail

TENANT="${1:-}"
SEARCH="${2:-}"
SITE_ARG="${3:-}"
WD_ARG="${4:-}"

if [ -z "$TENANT" ]; then
  echo '{"error": "Usage: scan-workday.sh TENANT [SEARCHTEXT] [SITE] [WD]", "total": 0, "jobs": []}'
  exit 1
fi

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

valid_segment() { # tenant/site/wd values must be plain identifiers; site in
  # particular comes from a remote robots.txt and must never reach an
  # interpolated context unvalidated.
  printf '%s' "$1" | grep -qE '^[A-Za-z0-9_-]+$'
}

try_site() { # wd site -> prints response on success, returns 0
  local wd="$1" site="$2"
  valid_segment "$wd" && valid_segment "$site" || return 1
  local url="https://${TENANT}.${wd}.myworkdayjobs.com/wday/cxs/${TENANT}/${site}/jobs"
  local resp
  resp=$(curl -s -m 8 -X POST "$url" \
    -H "Content-Type: application/json" -H "Accept: application/json" \
    -H "User-Agent: $UA" \
    -d "{\"appliedFacets\":{},\"limit\":20,\"offset\":0,\"searchText\":$(printf '%s' "$SEARCH" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    2>/dev/null) || return 1
  case "$resp" in
    '{"total'*) printf '%s' "$resp" | WD_TENANT="$TENANT" WD_WD="$wd" WD_SITE="$site" python3 -c '
import json, os, sys
data = json.load(sys.stdin)
tenant, wd, site = os.environ["WD_TENANT"], os.environ["WD_WD"], os.environ["WD_SITE"]
base = f"https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}"
jobs = data.get("jobPostings", []) or []
for j in jobs:
    j["externalUrl"] = base + j.get("externalPath", "")
print(json.dumps({"total": data.get("total", 0), "jobs": jobs,
                  "tenant": tenant, "site": site, "wd": wd}))'
      return 0;;
  esac
  return 1
}

valid_segment "$TENANT" || { echo '{"error": "invalid tenant", "total": 0, "jobs": []}'; exit 1; }

if [ -n "$SITE_ARG" ] && [ -n "$WD_ARG" ]; then
  try_site "$WD_ARG" "$SITE_ARG" && exit 0
  echo '{"total": 0, "jobs": []}'
  exit 0
fi

# Discovery: each tenant's robots.txt names its career site in the Sitemap
# line (e.g. "Sitemap: https://zillow.wd5.myworkdayjobs.com/Zillow_Group_External/siteMap.xml"),
# so discovery is one GET per cluster instead of brute-forcing site names.
FALLBACK=""
for wd in wd5 wd1 wd3 wd2 wd12 wd10; do
  robots=$(curl -s -m 6 -H "User-Agent: $UA" "https://${TENANT}.${wd}.myworkdayjobs.com/robots.txt" 2>/dev/null) || continue
  # A tenant can expose several sites (main careers + niche programs). Try
  # each; prefer the first that has matches for the query, but remember the
  # first valid responder as a fallback so "0 matches on the main board" is
  # still a definitive answer rather than a discovery failure.
  sites=$(printf '%s' "$robots" | grep -iE '^(Sitemap:|Allow:)' \
    | sed -E 's|^Sitemap:.*myworkdayjobs\.com/([^/]+)/siteMap.*|\1|i; s|^Allow: /([^/]+)/?$|\1|i' \
    | grep -vE '^(Sitemap:|Allow:)' | awk '!seen[$0]++' | head -5)
  for site in $sites; do
    resp=$(try_site "$wd" "$site") || continue
    total=$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("total",0))' 2>/dev/null || echo 0)
    if [ "$total" -gt 0 ]; then printf '%s' "$resp"; exit 0; fi
    [ -z "$FALLBACK" ] && FALLBACK="$resp"
  done
  [ -n "$FALLBACK" ] && { printf '%s' "$FALLBACK"; exit 0; }
done

echo '{"total": 0, "jobs": []}'
