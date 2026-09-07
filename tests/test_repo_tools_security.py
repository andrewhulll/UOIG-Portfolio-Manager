"""Security regression tests for the Ask-Claude repository reader."""
from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import repo_tools  # noqa: E402
from src.auth import workos_client as wc  # noqa: E402


class RepoToolSecurityTests(unittest.TestCase):
    def test_secret_text_files_are_never_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_names = (
                "supabase.url.txt",
                "workos.cookie.txt",
                "workos.client.txt",
                "deployment-password.yaml",
                "service_token.json",
            )
            for name in secret_names:
                (root / name).write_text("do-not-expose", encoding="utf-8")

            with mock.patch.object(repo_tools, "REPO", root):
                for name in secret_names:
                    content, is_error = repo_tools.read_file(name)
                    self.assertTrue(is_error)
                    self.assertNotIn("do-not-expose", content)

                listing = repo_tools.list_files()
                self.assertTrue(all(name not in listing for name in secret_names))
                self.assertNotIn("do-not-expose", repo_tools.search_repo("do-not-expose"))

    def test_only_explicitly_allowed_plain_text_file_is_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements.txt").write_text("fastapi", encoding="utf-8")
            (root / "notes.txt").write_text("private notes", encoding="utf-8")

            with mock.patch.object(repo_tools, "REPO", root):
                self.assertEqual(repo_tools.read_file("requirements.txt"), ("fastapi", False))
                self.assertTrue(repo_tools.read_file("notes.txt")[1])

    def test_cookie_password_accepts_only_a_32_byte_urlsafe_key(self):
        raw_key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")

        with mock.patch.object(wc, "_secret", return_value=raw_key):
            self.assertEqual(wc.cookie_password(), raw_key)
        with mock.patch.object(wc, "_secret", return_value=raw_key.rstrip("=")):
            self.assertEqual(wc.cookie_password(), raw_key)

        for weak_or_invalid in ("correct horse battery staple", "a" * 32,
                                "a" * 42, "+" * 43):
            with self.subTest(value=weak_or_invalid):
                with mock.patch.object(wc, "_secret", return_value=weak_or_invalid):
                    self.assertIsNone(wc.cookie_password())


if __name__ == "__main__":
    unittest.main()
