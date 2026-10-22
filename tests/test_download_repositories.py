import hashlib
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_repositories.py"
spec = importlib.util.spec_from_file_location("downloads", SCRIPT)
downloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloads)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "hermes-agent": {"repository": "NousResearch/hermes-agent", "ref": "main"},
            "second": {"repository": "example/second"},
        }

    def test_single_multiple_all_and_deduplication(self):
        self.assertEqual(len(downloads.select(self.registry, "hermes-agent")["include"]), 1)
        selected = downloads.select(self.registry, " second,hermes-agent,second ")["include"]
        self.assertEqual([item["id"] for item in selected], ["second", "hermes-agent"])
        self.assertEqual(selected[0]["ref"], "")
        self.assertEqual(len(downloads.select(self.registry, "all")["include"]), 2)

    def test_ref_override(self):
        self.assertTrue(all(item["ref"] == "v1.0" for item in downloads.select(self.registry, "all", "v1.0")["include"]))

    def test_invalid_selection_and_refs(self):
        for selection in ("", "unknown", "all,second", "second,", "../escape"):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                downloads.select(self.registry, selection)
        for ref in ("--upload-pack=bad", "bad\nref", "x..y", "$(touch bad)"):
            with self.subTest(ref=ref), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                downloads.select(self.registry, "second", ref)

    def test_invalid_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "repositories.json"
            for content in ('{}', '[]', '{"x":{},"x":{}}', '{"all":{"repository":"a/b"}}', '{"x":{"repository":"https://github.com/a/b"}}'):
                with self.subTest(content=content), self.assertRaises(ValueError):
                    config.write_text(content)
                    downloads.load_registry(config)

    def test_large_registry_can_be_selected_in_batches(self):
        registry = {"repo" + str(i): {"repository": "example/project"} for i in range(257)}
        self.assertEqual(len(downloads.select(registry, "repo0,repo256")["include"]), 2)
        with self.assertRaises(ValueError):
            downloads.select(registry, "all")


class ScheduleTests(unittest.TestCase):
    def test_five_day_interval_across_month_and_year(self):
        for start in ("2026-10-27T03:17:00+08:00", "2026-12-31T03:17:00+08:00"):
            first = datetime.fromisoformat(start)
            for offset in range(11):
                with self.subTest(start=start, offset=offset):
                    self.assertEqual(downloads.schedule_due(first + timedelta(days=offset)), offset % 5 == 0)

    def test_utc_is_converted_to_local_date(self):
        self.assertFalse(downloads.schedule_due(datetime.fromisoformat("2026-10-26T15:59:00+00:00")))
        self.assertTrue(downloads.schedule_due(datetime.fromisoformat("2026-10-26T19:17:00+00:00")))
        self.assertFalse(downloads.schedule_due(datetime.fromisoformat("2026-10-20T19:17:00+00:00")))
        with self.assertRaises(ValueError):
            downloads.schedule_due(datetime(2026, 10, 22))

    def test_schedule_skips_and_push_builds_all(self):
        registry = {"a": {"repository": "owner/one"}, "b": {"repository": "owner/two"}}
        between = datetime(2026, 10, 23, tzinfo=timezone(timedelta(hours=8)))
        due, matrix = downloads.select_for_event(registry, "schedule", now=between)
        self.assertFalse(due)
        self.assertEqual(matrix, {"include": []})
        due, matrix = downloads.select_for_event(registry, "push", now=between)
        self.assertTrue(due)
        self.assertEqual(len(matrix["include"]), 2)
        due, matrix = downloads.select_for_event(registry, "schedule", now=between + timedelta(days=4))
        self.assertTrue(due)
        self.assertEqual(len(matrix["include"]), 2)


class PackageTests(unittest.TestCase):
    def test_real_archive_preserves_git_history_tags_and_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "source"
            fixture.mkdir()

            def local_git(*args, cwd=fixture):
                return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()

            local_git("init", "-b", "main")
            local_git("config", "user.name", "Test")
            local_git("config", "user.email", "test@example.invalid")
            (fixture / "README.md").write_text("first\n")
            local_git("add", ".")
            local_git("commit", "-m", "first")
            local_git("tag", "v1")
            tagged_commit = local_git("rev-parse", "HEAD")
            (fixture / "README.md").write_text("second\n")
            local_git("commit", "-am", "second")
            original_git = downloads.git

            def fixture_git(*args, cwd=None):
                if args[0] == "clone":
                    # Exercise actual Git depth/tag behavior without a network dependency.
                    replacement = [fixture.as_uri() if value.startswith("https://github.com/") else value for value in args]
                    return local_git(*replacement, cwd=root)
                return original_git(*args, cwd=cwd)

            for ref, full_history, count in (("main", False, "1"), ("main", True, "2"), ("v1", True, "1")):
                with self.subTest(ref=ref, full_history=full_history):
                    output = root / (ref + str(full_history))
                    entry = {"id": "project", "repository": "example/project", "ref": ref}
                    with patch.object(downloads, "git", side_effect=fixture_git):
                        archive = downloads.package(entry, output, full_history=full_history)
                    expected_hash = (output / "SHA256SUMS.txt").read_text().split()[0]
                    self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), expected_hash)
                    with tarfile.open(archive) as bundle:
                        # The only source is this test's locally generated fixture.
                        bundle.extractall(output / "verify")
                    extracted = output / "verify" / "project"
                    self.assertEqual(original_git("rev-list", "--count", "HEAD", cwd=extracted), count)
                    self.assertEqual(original_git("rev-parse", "HEAD", cwd=extracted), (output / "COMMIT.txt").read_text().strip())
                    original_git("fsck", "--full", cwd=extracted)
                    if ref == "v1":
                        self.assertEqual(original_git("rev-parse", "HEAD", cwd=extracted), tagged_commit)
                    self.assertEqual(json.loads((output / "SOURCE.json").read_text())["full_history"], full_history)

    def test_failed_clone_does_not_publish_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(downloads, "git", side_effect=RuntimeError("unreachable")):
                with self.assertRaises(RuntimeError):
                    downloads.package({"id": "test", "repository": "a/b"}, directory)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
