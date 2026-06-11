#!/usr/bin/env python3
"""Apply whitelisted text edits to an IDML CV and repackage it safely.

Usage:
    python3 idml-apply.py --cv data/master-cv.idml --map data/story-map.json \
        --edits edits.json --out data/cv-drafts/CV-rabourn-acme-2026-06-15.idml

edits.json shape:
    {
      "u1a2": [ {"run": 1, "text": "New profile paragraph ..."} ],
      "u26b": [ {"run": 3, "text": "Figma, ..."} ]
    }

Story ids and run indexes refer to the story map (idml-story-map.py), which
lists every editable story's runs in document order. Guarantees:

- Only stories marked editable in the map can be edited.
- Replacement happens at the level of individual <Content> text runs via
  surgical string substitution; every byte outside the replaced run is
  untouched, so styles, geometry, and spreads cannot drift.
- Length budget: each replacement must stay within +/-N% of the original
  run's character count (default 10, --budget-pct to change), to limit
  overset risk. The script cannot render frames; always check for overset
  in InDesign.
- No em dashes in replacement text (PRD content rule).
- The CV's mtime must match the map's generated_from_mtime (stale map = error).
- Every modified story is re-validated as well-formed XML.
- Repackaging follows IDML rules: mimetype is the first entry, stored
  uncompressed; no directory entries.

Exit code 0 and a JSON change summary on stdout on success; nonzero with a
message on stderr otherwise (the output file is never written on failure).
"""

import argparse
import json
import os
import re
import sys
import zipfile

# Reuse the parsing helpers from idml-story-map.py (hyphenated filename).
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "idml_story_map", os.path.join(os.path.dirname(os.path.abspath(__file__)), "idml-story-map.py"))
_story_map_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_story_map_mod)
safe_parse_xml = _story_map_mod.safe_parse_xml
CONTENT_RE = _story_map_mod.CONTENT_RE

EM_DASH = "—"


def escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def apply_edits_to_story(xml_text, edits, story, budget_pct):
    """Replace the text of specific Content runs. Returns (new_xml, changes)."""
    matches = list(CONTENT_RE.finditer(xml_text))
    changes = []
    # Apply right-to-left so earlier match offsets stay valid.
    for edit in sorted(edits, key=lambda e: e["run"], reverse=True):
        idx = edit["run"]
        new_text = edit["text"]
        if not (0 <= idx < len(matches)):
            raise ValueError(f"story {story['id']}: run {idx} out of range (0-{len(matches)-1})")
        if EM_DASH in new_text:
            raise ValueError(f"story {story['id']} run {idx}: replacement contains an em dash")
        run_info = next((r for r in (story.get("runs") or []) if r["index"] == idx), None)
        old_raw = matches[idx].group(1)
        old_len = run_info["chars"] if run_info else len(old_raw)
        lo = old_len * (1 - budget_pct / 100.0)
        hi = old_len * (1 + budget_pct / 100.0)
        if not (lo <= len(new_text) <= hi):
            raise ValueError(
                f"story {story['id']} run {idx}: length {len(new_text)} outside "
                f"budget {lo:.0f}-{hi:.0f} (original {old_len}, +/-{budget_pct}%)")
        start, end = matches[idx].span(1)
        xml_text = xml_text[:start] + escape(new_text) + xml_text[end:]
        changes.append({
            "story": story["id"], "run": idx,
            "old_chars": old_len, "new_chars": len(new_text),
            "old_text": run_info["text"] if run_info else old_raw,
            "new_text": new_text,
        })
    safe_parse_xml(xml_text, story["file"])
    return xml_text, changes


def repackage(src_path, out_path, replacements):
    """Write a new IDML: mimetype first and stored, everything else deflated.

    `replacements` maps archive names to new bytes.
    """
    with zipfile.ZipFile(src_path) as src:
        names = [n for n in src.namelist() if not n.endswith("/")]
        if "mimetype" not in names:
            raise ValueError("source IDML has no mimetype entry")
        ordered = ["mimetype"] + [n for n in names if n != "mimetype"]
        with zipfile.ZipFile(out_path, "w") as out:
            for name in ordered:
                data = replacements.get(name, src.read(name))
                compress = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                out.writestr(zipfile.ZipInfo(name), data, compress_type=compress)


def main():
    parser = argparse.ArgumentParser(description="Apply whitelisted edits to an IDML CV")
    parser.add_argument("--cv", required=True)
    parser.add_argument("--map", required=True, dest="map_path")
    parser.add_argument("--edits", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--budget-pct", type=float, default=10.0)
    parser.add_argument("--allow-stale-map", action="store_true",
                        help="Skip the CV mtime check (use only when you know the map is current)")
    args = parser.parse_args()

    with open(args.map_path) as fh:
        story_map = json.load(fh)
    with open(args.edits) as fh:
        edits = json.load(fh)

    if not args.allow_stale_map:
        actual = os.path.getmtime(args.cv)
        recorded = story_map.get("generated_from_mtime")
        if recorded is None or abs(actual - recorded) > 1:
            print("Story map is stale: the CV file changed since the map was generated. "
                  "Regenerate with idml-story-map.py first.", file=sys.stderr)
            sys.exit(1)

    stories_by_id = {s["id"]: s for s in story_map["stories"]}
    replacements = {}
    all_changes = []
    for story_id, story_edits in edits.items():
        story = stories_by_id.get(story_id)
        if story is None:
            print(f"Unknown story id: {story_id}", file=sys.stderr)
            sys.exit(1)
        if not story.get("editable"):
            print(f"Story {story_id} ({story.get('role')}) is not on the editable whitelist", file=sys.stderr)
            sys.exit(1)
        with zipfile.ZipFile(args.cv) as zf:
            xml_text = zf.read(story["file"]).decode("utf-8")
        try:
            new_xml, changes = apply_edits_to_story(xml_text, story_edits, story, args.budget_pct)
        except ValueError as e:
            print(f"Edit rejected: {e}", file=sys.stderr)
            sys.exit(1)
        replacements[story["file"]] = new_xml.encode("utf-8")
        all_changes.extend(changes)

    if not all_changes:
        print("No edits to apply", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    repackage(args.cv, args.out, replacements)

    # Verify the output round-trips: valid zip, mimetype first and stored,
    # all XML well-formed.
    with zipfile.ZipFile(args.out) as check:
        infos = check.infolist()
        assert infos[0].filename == "mimetype", "mimetype is not the first entry"
        assert infos[0].compress_type == zipfile.ZIP_STORED, "mimetype is compressed"
        for info in infos:
            if info.filename.endswith(".xml"):
                safe_parse_xml(check.read(info.filename).decode("utf-8"), info.filename)

    summary = {
        "output": args.out,
        "stories_modified": sorted(replacements.keys()),
        "changes": all_changes,
        "reminder": "Open in InDesign and check for overset text; the script cannot render frames.",
    }
    print(f"Wrote {args.out} ({len(all_changes)} run replacements in {len(replacements)} stories)", file=sys.stderr)
    json.dump(summary, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
