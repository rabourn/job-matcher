#!/usr/bin/env python3
"""Tests for idml-story-map.py and idml-apply.py using a synthetic IDML.

Run:  python3 test/test_idml_tools.py
"""

import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_SCRIPT = os.path.join(ROOT, "scripts", "idml-story-map.py")
APPLY_SCRIPT = os.path.join(ROOT, "scripts", "idml-apply.py")

PROFILE_TEXT = "I lead design at the intersection of strategy and product across many domains."
STORY_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="15.0">
  <Story Self="{sid}">
    <ParagraphStyleRange>
      <CharacterStyleRange><Content>{head}</Content></CharacterStyleRange>
      <CharacterStyleRange><Content>{body}</Content></CharacterStyleRange>
    </ParagraphStyleRange>
  </Story>
</idPkg:Story>
"""


def build_fixture(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.adobe.indesign-idml-package",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("designmap.xml", '<?xml version="1.0"?><Document/>')
        zf.writestr("Stories/Story_p1.xml",
                    STORY_TEMPLATE.format(sid="p1", head="PROFILE", body=PROFILE_TEXT))
        zf.writestr("Stories/Story_e1.xml",
                    STORY_TEMPLATE.format(sid="e1", head="EDUCATION", body="PhD coursework and more."))


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main():
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  ok: {name}")
        else:
            failures.append(name)
            print(f"  FAIL: {name} {detail}")

    with tempfile.TemporaryDirectory() as tmp:
        cv = os.path.join(tmp, "cv.idml")
        map_path = os.path.join(tmp, "map.json")
        build_fixture(cv)

        r = run([sys.executable, MAP_SCRIPT, "--cv", cv, "--out", map_path])
        check("story map generates", r.returncode == 0, r.stderr)
        story_map = json.load(open(map_path))
        roles = {s["id"]: (s["role"], s["editable"]) for s in story_map["stories"]}
        check("profile editable", roles.get("p1") == ("profile", True), str(roles))
        check("education locked", roles.get("e1") == ("education", False), str(roles))

        def apply(edits, out_name, extra=None):
            edits_path = os.path.join(tmp, "edits.json")
            json.dump(edits, open(edits_path, "w"))
            return run([sys.executable, APPLY_SCRIPT, "--cv", cv, "--map", map_path,
                        "--edits", edits_path, "--out", os.path.join(tmp, out_name)] + (extra or []))

        new_text = PROFILE_TEXT.replace("many domains", "key sectors")  # within budget
        r = apply({"p1": [{"run": 1, "text": new_text}]}, "ok.idml")
        check("valid edit applies", r.returncode == 0, r.stderr)

        with zipfile.ZipFile(os.path.join(tmp, "ok.idml")) as zf:
            infos = zf.infolist()
            check("mimetype first", infos[0].filename == "mimetype")
            check("mimetype stored", infos[0].compress_type == zipfile.ZIP_STORED)
            check("edit landed", new_text.encode() in zf.read("Stories/Story_p1.xml"))
            check("other story untouched",
                  zf.read("Stories/Story_e1.xml") == zipfile.ZipFile(cv).read("Stories/Story_e1.xml"))

        r = apply({"e1": [{"run": 1, "text": "hacked education text!!"}]}, "no1.idml")
        check("non-whitelisted story rejected", r.returncode != 0 and "whitelist" in r.stderr)

        r = apply({"p1": [{"run": 1, "text": "too short"}]}, "no2.idml")
        check("length budget enforced", r.returncode != 0 and "budget" in r.stderr)

        r = apply({"p1": [{"run": 1, "text": PROFILE_TEXT[:-1] + "—"}]}, "no3.idml")
        check("em dash rejected", r.returncode != 0 and "em dash" in r.stderr)

        r = apply({"p1": [{"run": 1, "text": PROFILE_TEXT.replace("strategy", "str&tegy")}]}, "esc.idml")
        check("special chars escape cleanly", r.returncode == 0, r.stderr)
        if r.returncode == 0:
            with zipfile.ZipFile(os.path.join(tmp, "esc.idml")) as zf:
                check("ampersand escaped in XML", b"str&amp;tegy" in zf.read("Stories/Story_p1.xml"))

        st = os.stat(cv)
        os.utime(cv, (st.st_atime, st.st_mtime + 60))  # simulate a replaced CV
        r = apply({"p1": [{"run": 1, "text": new_text}]}, "no4.idml")
        check("stale map detected after CV change", r.returncode != 0 and "stale" in r.stderr.lower())

    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed")


if __name__ == "__main__":
    main()
