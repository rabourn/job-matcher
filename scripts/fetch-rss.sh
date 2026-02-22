#!/bin/bash
# Fetch an RSS/Atom feed and convert it to JSON.
#
# Usage:
#   fetch-rss.sh FEED_URL
#
# Examples:
#   fetch-rss.sh "https://weworkremotely.com/categories/remote-design-jobs.rss"
#   fetch-rss.sh "https://remotive.com/remote-jobs/design/feed"
#
# Output: JSON with {feed_url, fetched_at, items: [{title, link, pubDate, description, category, company, author}]}

set -euo pipefail

FEED_URL="${1:-}"

if [ -z "$FEED_URL" ]; then
  echo '{"error": "Usage: fetch-rss.sh FEED_URL"}' >&2
  echo '{"items": []}'
  exit 1
fi

# Fetch the feed
xml_content=$(curl -s -L \
  -H "User-Agent: JobMatcher/2.0 (job search tool)" \
  "$FEED_URL" 2>/dev/null) || {
  echo "Error fetching $FEED_URL" >&2
  echo '{"items": []}'
  exit 0
}

if [ -z "$xml_content" ]; then
  echo "Empty response from $FEED_URL" >&2
  echo '{"items": []}'
  exit 0
fi

# Parse XML to JSON using Python
echo "$xml_content" | python3 -c "
import sys
import json
import xml.etree.ElementTree as ET
from datetime import datetime

xml_input = sys.stdin.read()
items = []

try:
    root = ET.fromstring(xml_input)
except ET.ParseError as e:
    print(json.dumps({'items': [], 'error': str(e)}))
    sys.exit(0)

# Handle RSS 2.0
for item in root.findall('.//item'):
    entry = {
        'title': '',
        'link': '',
        'pubDate': '',
        'description': '',
        'category': '',
        'company': '',
        'author': '',
        'location': '',
    }
    for child in item:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        text = (child.text or '').strip()
        if tag == 'title':
            entry['title'] = text
        elif tag == 'link':
            entry['link'] = text
        elif tag == 'pubDate':
            entry['pubDate'] = text
        elif tag == 'description':
            entry['description'] = text
        elif tag == 'category':
            if entry['category']:
                entry['category'] += ', ' + text
            else:
                entry['category'] = text
        elif tag == 'author' or tag == 'creator':
            entry['author'] = text
        elif tag == 'region' or tag == 'location':
            entry['location'] = text
    # Try to extract company from title (common pattern: 'Title at Company')
    if ' at ' in entry['title'] and not entry['company']:
        parts = entry['title'].rsplit(' at ', 1)
        if len(parts) == 2:
            entry['company'] = parts[1].strip()
    items.append(entry)

# Handle Atom feeds
ns = {'atom': 'http://www.w3.org/2005/Atom'}
for entry_el in root.findall('.//atom:entry', ns):
    entry = {
        'title': '',
        'link': '',
        'pubDate': '',
        'description': '',
        'category': '',
        'company': '',
        'author': '',
        'location': '',
    }
    title_el = entry_el.find('atom:title', ns)
    if title_el is not None:
        entry['title'] = (title_el.text or '').strip()
    link_el = entry_el.find('atom:link', ns)
    if link_el is not None:
        entry['link'] = link_el.get('href', '')
    published_el = entry_el.find('atom:published', ns) or entry_el.find('atom:updated', ns)
    if published_el is not None:
        entry['pubDate'] = (published_el.text or '').strip()
    summary_el = entry_el.find('atom:summary', ns) or entry_el.find('atom:content', ns)
    if summary_el is not None:
        entry['description'] = (summary_el.text or '').strip()
    cat_el = entry_el.find('atom:category', ns)
    if cat_el is not None:
        entry['category'] = cat_el.get('term', '') or (cat_el.text or '').strip()
    author_el = entry_el.find('atom:author/atom:name', ns)
    if author_el is not None:
        entry['author'] = (author_el.text or '').strip()
    if ' at ' in entry['title'] and not entry['company']:
        parts = entry['title'].rsplit(' at ', 1)
        if len(parts) == 2:
            entry['company'] = parts[1].strip()
    items.append(entry)

result = {
    'feed_url': '$FEED_URL',
    'fetched_at': datetime.utcnow().isoformat() + 'Z',
    'item_count': len(items),
    'items': items,
}
print(json.dumps(result, indent=2))
"
