"""U-22 (SPEC 9.3, 6.4, DEC-6.4): "interface freeze v2" (v1 plus ``ExportOptions.raise_quota_max``, DECISION D11).

The SHA-256 of ``Addon/mvarlib/api.py`` and ``Addon/mvarlib/errors.py`` must equal the record in
``tests/golden/interface_sha256.json`` (also written into NOTES.md). Changing either file needs
both teams to agree (G3/G5 and G4); the record is then updated deliberately, in the same change
and with a NOTES.md entry. Line endings are normalised to LF before hashing so a checkout with
CRLF conversion (the repo has ``* text=auto``) hashes the same; on this machine the bytes are LF.

Gate G5 changed ``api.py`` once (freeze v2) and may not edit NOTES.md: the orchestrator merges the
gate notes. Until it has, the new hash is recorded in ``docs/mvar/notes/G5.md``; the NOTES test below
therefore accepts the hash in NOTES.md or in any ``docs/mvar/notes/*.md``, and the history test pins
the v1 hashes (``errors.py`` did not change).
"""
import hashlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GOLDEN = os.path.join(REPO, "tests", "golden", "interface_sha256.json")
FROZEN = ("Addon/mvarlib/api.py", "Addon/mvarlib/errors.py")


def frozen_sha256(rel):
    with open(os.path.join(REPO, *rel.split("/")), "rb") as fh:
        data = fh.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


class TestInterfaceFrozen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(GOLDEN, "r", encoding="utf-8") as fh:
            cls.record = json.load(fh)

    def test_record_names_exactly_the_two_frozen_files(self):
        self.assertEqual(self.record["schema"], "mvarlib.interface_sha256/1")
        self.assertEqual(sorted(self.record["files"]), sorted(FROZEN))
        for digest in self.record["files"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_api_py_is_frozen(self):
        self.assertEqual(frozen_sha256("Addon/mvarlib/api.py"), self.record["files"]["Addon/mvarlib/api.py"],
                         "api.py changed: interface freeze v1 is broken. Needs agreement of G3/G5 and G4; "
                         "update tests/golden/interface_sha256.json and NOTES.md together.")

    def test_errors_py_is_frozen(self):
        self.assertEqual(frozen_sha256("Addon/mvarlib/errors.py"), self.record["files"]["Addon/mvarlib/errors.py"],
                         "errors.py changed: interface freeze v1 is broken. Needs agreement of G3/G5 and G4; "
                         "update tests/golden/interface_sha256.json and NOTES.md together.")

    def test_notes_record_the_same_hashes(self):
        notes = os.path.join(REPO, "NOTES.md")
        with open(notes, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("interface freeze v1", text.lower())
        texts = [text]
        notes_dir = os.path.join(REPO, "docs", "mvar", "notes")
        for name in sorted(os.listdir(notes_dir)):
            if name.endswith(".md"):
                with open(os.path.join(notes_dir, name), "r", encoding="utf-8") as fh:
                    texts.append(fh.read())
        for rel, digest in self.record["files"].items():
            self.assertTrue(any(digest in t for t in texts),
                            "neither NOTES.md nor docs/mvar/notes/*.md records the SHA-256 of " + rel)

    def test_freeze_v2_history(self):
        v1 = self.record["v1"]
        self.assertEqual(sorted(v1), sorted(FROZEN))
        self.assertNotEqual(v1["Addon/mvarlib/api.py"], self.record["files"]["Addon/mvarlib/api.py"])
        self.assertEqual(v1["Addon/mvarlib/errors.py"], self.record["files"]["Addon/mvarlib/errors.py"],
                         "freeze v2 changed api.py only; errors.py must be unchanged")
        self.assertIn("v2", self.record["freeze"])


if __name__ == "__main__":
    unittest.main()
