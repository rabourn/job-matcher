#!/usr/bin/env python3
"""Generate the story map for an IDML CV template.

Usage:
    python3 idml-story-map.py --cv data/master-cv.idml --out data/story-map.json
    python3 idml-story-map.py --cv data/master-cv.idml          # preview to stdout

Unzips the IDML (in memory), extracts the text runs of every story, classifies
each story into a role using leading-keyword heuristics, and assigns editable
defaults. The pipeline (screen-alerts skill) presents the inferred map for
confirmation on first use and regenerates it whenever the CV file's mtime no
longer matches `generated_from_mtime`.

Only stories marked editable may be touched by idml-apply.py, and only via
run-level text replacement. Roles:

  profile, core_strengths, experience, methods, earlier_career, letter,
  tagline, name, contact, header, education, languages, other

Editable by default: profile, core_strengths, experience, methods, letter.
Everything else defaults to editable: false. Edit the JSON by hand to widen
or narrow the whitelist; regeneration preserves nothing, so re-apply manual
overrides after a template change.
"""

import argparse
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

CONTENT_RE = re.compile(r"<Content>(.*?)</Content>", re.S)


def safe_parse_xml(xml_text, name=""):
    """Parse XML after rejecting DOCTYPE/ENTITY declarations.

    Legitimate IDML never contains these; refusing them up front neutralizes
    XXE and entity-expansion attacks without a defusedxml dependency.
    """
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise ValueError(f"Refusing to parse {name or 'XML'}: contains DOCTYPE/ENTITY declaration")
    return ET.fromstring(xml_text)

ROLE_RULES = [
    # (role, editable, predicate on full uppercase-insensitive text)
    ("profile", True, lambda t: t.upper().startswith("PROFILE")),
    ("core_strengths", True, lambda t: t.upper().startswith("CORE STRENGTHS")),
    ("experience", True, lambda t: t.upper().startswith("EXPERIENCE")),
    ("methods", True, lambda t: t.upper().startswith(("METHODS, TOOLS", "METHODS & TOOLS", "METHODS AND TOOLS"))),
    ("earlier_career", True, lambda t: t.upper().startswith("EARLIER CAREER")),
    ("letter", True, lambda t: t.upper().startswith(("DEAR", "COVER LETTER", "TO THE HIRING"))),
    ("education", False, lambda t: t.upper().startswith("EDUCATION") or "DISSERTATION" in t.upper()[:120] or t.upper().startswith("PHD")),
    ("languages", False, lambda t: t.upper().startswith("LANGUAGES")),
    ("header", False, lambda t: bool(re.match(r"^\S+\s+pg\.", t))),
    ("contact", False, lambda t: "@" in t[:80]),
]


def unescape(text):
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
                .replace("&apos;", "'").replace("&amp;", "&"))


def extract_runs(xml_text):
    """Content runs in document order, matching idml-apply.py's enumeration."""
    return [unescape(m.group(1)) for m in CONTENT_RE.finditer(xml_text)]


def classify(full_text, cv_name=""):
    text = full_text.strip()
    for role, editable, predicate in ROLE_RULES:
        if predicate(text):
            return role, editable
    # A short story matching the person's name from the filename or all-caps
    if len(text) <= 40 and text == text.upper() and len(text.split()) <= 4 and text:
        return "name", False
    if 40 < len(text) <= 160:
        return "tagline", False
    return "other", False


def build_map(cv_path):
    stories = []
    with zipfile.ZipFile(cv_path) as zf:
        story_names = sorted(n for n in zf.namelist() if n.startswith("Stories/") and n.endswith(".xml"))
        for name in story_names:
            xml_text = zf.read(name).decode("utf-8")
            # Sanity: the raw XML must parse (and contain no entity tricks)
            safe_parse_xml(xml_text, name)
            runs = extract_runs(xml_text)
            full_text = " ".join(" ".join(runs).split())
            story_id = re.sub(r"^Stories/Story_(.+)\.xml$", r"\1", name)
            role, editable = classify(full_text)
            stories.append({
                "id": story_id,
                "file": name,
                "role": role,
                "editable": editable,
                "chars": sum(len(r) for r in runs),
                "run_count": len(runs),
                "runs": [{"index": i, "chars": len(r), "text": r} for i, r in enumerate(runs)] if editable else None,
                "preview": full_text[:200],
            })
    # If two stories claim the same exclusive role, keep the longer one and
    # demote the rest to "other" so the whitelist stays unambiguous.
    for role in ("profile", "core_strengths", "experience", "methods", "letter"):
        claimants = [s for s in stories if s["role"] == role]
        for s in sorted(claimants, key=lambda s: -s["chars"])[1:]:
            s["role"] = "other"
            s["editable"] = False
            s["runs"] = None
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_from": os.path.abspath(cv_path),
        "generated_from_mtime": os.path.getmtime(cv_path),
        "stories": stories,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate IDML story map")
    parser.add_argument("--cv", required=True, help="Path to the IDML file")
    parser.add_argument("--out", help="Write JSON here (default: stdout)")
    args = parser.parse_args()

    if not os.path.exists(args.cv):
        print(f"CV not found: {args.cv}", file=sys.stderr)
        sys.exit(1)

    story_map = build_map(args.cv)

    editable = [s for s in story_map["stories"] if s["editable"]]
    print(f"{len(story_map['stories'])} stories, {len(editable)} editable:", file=sys.stderr)
    for s in story_map["stories"]:
        flag = "EDIT" if s["editable"] else "    "
        print(f"  [{flag}] {s['id']:<6} {s['role']:<15} {s['chars']:>5} chars  {s['preview'][:60]}", file=sys.stderr)

    output = json.dumps(story_map, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(output)
        print(f"Story map written to {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
