"""Isolated browser metadata fixtures; no user's browsers are accessed."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import browser_inventory as b


class BrowserInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.home = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def browser(self, relative):
        root = self.home / relative
        root.mkdir(parents=True)
        (root / "Local State").write_text(json.dumps({"profile": {"info_cache": {
            "Default": {"name": "Primary", "user_name": "must-not-emit@example.test"},
            "../../outside": {"name": "bad"}}}}))
        for name in ["Default", "Profile 1"]:
            path = root / name; path.mkdir()
            with closing(sqlite3.connect(path / "Cookies")) as c:
                with c:
                    c.execute("CREATE TABLE cookies(host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)")
                    c.executemany("INSERT INTO cookies VALUES(?,?,?,?)", [(h, "cookie", "fixture-secret", b"fixture-secret")
                        for h in [".claude.ai", "api.claude.ai", "anthropic.com", "upclaude.com", "notclaude.ai.example.org"]])
        return root

    def test_macos_and_windows_profile_enumeration_and_exact_cookie_domains(self):
        for platform, relative in [("darwin", "Library/Application Support/Google/Chrome"),
                                   ("win32", "AppData/Local/Google/Chrome/User Data")]:
            root = self.browser(relative)
            with patch.dict(os.environ, {"LOCALAPPDATA": str(self.home / "AppData/Local"),
                                         "APPDATA": str(self.home / "AppData/Roaming")}):
                result = b.inventory(self.home, platform)
            chrome = next(item for item in result if item["browser"] == "Chrome")
            self.assertEqual(len(chrome["profiles"]), 2)
            for profile in chrome["profiles"]:
                self.assertEqual(profile["cookies"][0]["official_domain_cookie_counts"],
                                 {"claude.ai": 2, "claude.com": 0, "anthropic.com": 1})
            text = json.dumps(result)
            self.assertNotIn("fixture-secret", text); self.assertNotIn("must-not-emit", text)
            with closing(sqlite3.connect(root / "Default/Cookies")) as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM cookies").fetchone()[0], 5)

    def test_unreadable_or_unknown_schema_is_not_reported_as_zero(self):
        db = self.home / "bad.db"; db.write_text("not a database")
        result = b.counts(db)
        self.assertEqual(result["status"], "not_verified")
        self.assertNotIn("official_domain_cookie_counts", result)

    def test_firefox_registered_profiles_are_listed_without_querying_cookies(self):
        firefox = self.home / "AppData/Roaming/Mozilla/Firefox"; firefox.mkdir(parents=True)
        (firefox / "profiles.ini").write_text("[Profile0]\nName=Work\nIsRelative=1\nPath=Profiles/work.default\n")
        with patch.dict(os.environ, {"APPDATA": str(self.home / "AppData/Roaming"),
                                     "LOCALAPPDATA": str(self.home / "AppData/Local")}):
            result = b.inventory(self.home, "win32")
        self.assertEqual(result[0]["profiles"][0]["directory"], str(firefox / "Profiles/work.default"))


if __name__ == "__main__":
    unittest.main()
