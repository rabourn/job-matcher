#!/usr/bin/env python3
"""Parse RSS/Atom XML from stdin and output JSON.

Standalone version of the inline parser from fetch-rss.sh.
Used in Desktop mode where MCP fetches raw XML and we need to
convert it before piping to normalize-jobs.py.

Usage:
    cat feed.xml | python3 parse-rss.py [--feed-url URL]

Output: JSON with {feed_url, fetched_at, item_count, items: [{title, link, pubDate, ...}]}
"""

import sys
import json
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime


def parse_rss_xml(xml_input, feed_url=""):
    items = []

    try:
        root = ET.fromstring(xml_input)
    except ET.ParseError as e:
        return {"items": [], "error": str(e)}

    # Handle RSS 2.0
    for item in root.findall(".//item"):
        entry = {
            "title": "",
            "link": "",
            "pubDate": "",
            "description": "",
            "category": "",
            "company": "",
            "author": "",
            "location": "",
        }
        for child in item:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            text = (child.text or "").strip()
            if tag == "title":
                entry["title"] = text
            elif tag == "link":
                entry["link"] = text
            elif tag == "pubDate":
                entry["pubDate"] = text
            elif tag == "description":
                entry["description"] = text
            elif tag == "category":
                if entry["category"]:
                    entry["category"] += ", " + text
                else:
                    entry["category"] = text
            elif tag in ("author", "creator"):
                entry["author"] = text
            elif tag in ("region", "location"):
                entry["location"] = text
        # Extract company from "Title at Company" pattern
        if " at " in entry["title"] and not entry["company"]:
            parts = entry["title"].rsplit(" at ", 1)
            if len(parts) == 2:
                entry["company"] = parts[1].strip()
        items.append(entry)

    # Handle Atom feeds
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry_el in root.findall(".//atom:entry", ns):
        entry = {
            "title": "",
            "link": "",
            "pubDate": "",
            "description": "",
            "category": "",
            "company": "",
            "author": "",
            "location": "",
        }
        title_el = entry_el.find("atom:title", ns)
        if title_el is not None:
            entry["title"] = (title_el.text or "").strip()
        link_el = entry_el.find("atom:link", ns)
        if link_el is not None:
            entry["link"] = link_el.get("href", "")
        published_el = entry_el.find("atom:published", ns) or entry_el.find(
            "atom:updated", ns
        )
        if published_el is not None:
            entry["pubDate"] = (published_el.text or "").strip()
        summary_el = entry_el.find("atom:summary", ns) or entry_el.find(
            "atom:content", ns
        )
        if summary_el is not None:
            entry["description"] = (summary_el.text or "").strip()
        cat_el = entry_el.find("atom:category", ns)
        if cat_el is not None:
            entry["category"] = cat_el.get("term", "") or (
                cat_el.text or ""
            ).strip()
        author_el = entry_el.find("atom:author/atom:name", ns)
        if author_el is not None:
            entry["author"] = (author_el.text or "").strip()
        if " at " in entry["title"] and not entry["company"]:
            parts = entry["title"].rsplit(" at ", 1)
            if len(parts) == 2:
                entry["company"] = parts[1].strip()
        items.append(entry)

    return {
        "feed_url": feed_url,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "item_count": len(items),
        "items": items,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse RSS/Atom XML to JSON")
    parser.add_argument(
        "--feed-url", default="", help="Original feed URL (for metadata)"
    )
    args = parser.parse_args()

    xml_input = sys.stdin.read()
    result = parse_rss_xml(xml_input, args.feed_url)
    print(json.dumps(result, indent=2))
