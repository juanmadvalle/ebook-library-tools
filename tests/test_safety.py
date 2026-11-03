"""Fault injection and untrusted-record tests use disposable synthetic books."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_organizer import epub
from ebook_library_tools.cli import main
from ebook_library_tools import organizer as org
from ebook_library_tools.records import read_record


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_saved_plan_is_exact_and_ignores_new_books(self):
        source = epub(self.root / "Series/a.epub")
        target = self.root / "plan.json"
        self.assertEqual(main(["--root", str(self.root), "--save-plan", str(target)]), 0)
        new_book = epub(self.root / "Series/b.epub")
        self.assertEqual(main(["--root", str(self.root), "--apply-plan", str(target)]), 0)
        self.assertFalse(source.exists())
        self.assertTrue(new_book.exists())

    def test_stale_plan_and_case_collision_abort_without_state(self):
        source = epub(self.root / "Series/a.epub")
        target = self.root / "plan.json"
        moves = org.plan(self.root)
        org.save_plan(self.root, moves, target)
        original = source.read_bytes()
        source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            org.load_plan(self.root, target)
        source.write_bytes(original)
        (self.root / moves[0].destination.name.upper()).write_bytes(b"occupied")
        with self.assertRaises(ValueError):
            org.load_plan(self.root, target)
        self.assertFalse((self.root / org.STATE_DIR).exists())

    def test_plan_tampering_is_rejected(self):
        epub(self.root / "Series/a.epub")
        target = self.root / "plan.json"
        org.save_plan(self.root, org.plan(self.root), target)
        data = json.loads(target.read_text())
        for value in ("../outside.epub", "C:/outside.epub", "dir/../../outside.epub",
                      "a.epub:stream", "/absolute.epub", "CON.epub"):
            with self.subTest(value=value):
                data["entries"][0]["source"] = value
                target.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    org.load_plan(self.root, target)
        self.assertFalse((self.root / org.STATE_DIR).exists())

    def test_duplicate_plan_and_wrong_root_rejected(self):
        epub(self.root / "Series/a.epub")
        target = self.root / "plan.json"
        org.save_plan(self.root, org.plan(self.root), target)
        data = json.loads(target.read_text())
        data["entries"] *= 2
        target.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            org.load_plan(self.root, target)
        data["root"] = "another-library"
        target.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            org.load_plan(self.root, target)

    def test_all_journal_failure_boundaries_preserve_recovery(self):
        # First journal, backup recorded, copy recorded, move recorded.
        for fail_at in range(1, 5):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                source = epub(root / "Series/book.epub")
                original = source.read_bytes()
                real_write = org.write_journal
                calls = 0
                def fail_write(path, data):
                    nonlocal calls
                    calls += 1
                    if calls == fail_at:
                        raise OSError("simulated journal write failure")
                    real_write(path, data)
                with patch.object(org, "write_journal", side_effect=fail_write):
                    with self.assertRaises(OSError):
                        org.apply(root, org.plan(root))
                manifests = list((root / org.STATE_DIR).glob("*/manifest.json"))
                if fail_at == 1:
                    self.assertEqual(source.read_bytes(), original)
                    self.assertEqual(manifests, [])
                else:
                    report = org.inspect_recovery(root, manifests[0])
                    self.assertEqual(report[0]["backup_state"], "verified")
                    org.restore(root, manifests[0])
                    self.assertEqual(source.read_bytes(), original)

    def test_failed_backup_reports_pending_and_leaves_source(self):
        source = epub(self.root / "Series/book.epub")
        with patch.object(org, "copy_exclusive", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                org.apply(self.root, org.plan(self.root))
        manifest = next((self.root / org.STATE_DIR).glob("*/manifest.json"))
        report = org.inspect_recovery(self.root, manifest)[0]
        self.assertEqual(report["recorded"], "planned")
        self.assertEqual(report["original"], "verified")
        self.assertEqual(org.restore(self.root, manifest), 0)
        self.assertTrue(source.exists())

    def test_recovery_preflights_later_entry_before_any_write(self):
        a = epub(self.root / "Series/a.epub")
        b = epub(self.root / "Series/b.epub")
        manifest = org.apply(self.root, org.plan(self.root))
        data = json.loads(manifest.read_text())
        (manifest.parent / data["entries"][0]["backup"]).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            org.restore(self.root, manifest)
        self.assertFalse(a.exists())
        self.assertFalse(b.exists())

    def test_malformed_manifest_prevents_partial_restoration(self):
        source = epub(self.root / "Series/a.epub")
        manifest = org.apply(self.root, org.plan(self.root))
        data = json.loads(manifest.read_text())
        data["entries"].append({**data["entries"][0], "source": "../outside.epub"})
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            org.restore(self.root, manifest)
        self.assertFalse(source.exists())

    def test_v1_manifest_remains_compatible(self):
        source = epub(self.root / "Series/a.epub")
        manifest = org.apply(self.root, org.plan(self.root))
        data = json.loads(manifest.read_text())
        data["version"] = 1
        data["entries"][0]["source"] = "Series\\a.epub"
        manifest.write_text(json.dumps(data))
        self.assertEqual(org.restore(self.root, manifest), 1)
        self.assertTrue(source.exists())

    def test_link_in_parent_chain_is_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "alias"
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires permission on this host")
        with self.assertRaises(ValueError):
            org.checked_root(link)

    def test_csv_protects_formulas_and_raw_is_explicit(self):
        epub(self.root / "book.epub", "@SUM(1)", "=1+1")
        safe = org.export_csv(self.root)
        raw = org.export_csv(self.root, raw=True)
        with safe.open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["Title"], "'=1+1")
        self.assertEqual(row["Author"], "'@SUM(1)")
        with raw.open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(next(csv.DictReader(stream))["Title"], "=1+1")
        self.assertEqual(org.spreadsheet_cell("  -1"), "'  -1")

    def test_records_reject_duplicate_keys_and_oversize(self):
        path = self.root / "invalid.json"
        path.write_text('{"version":1,"version":2}')
        with self.assertRaises(ValueError):
            read_record(path)
        path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            read_record(path)

    def test_long_metadata_has_bounded_destination(self):
        epub(self.root / "Series/book.epub", "A" * 500, "B" * 500)
        moves = org.plan(self.root)
        self.assertLessEqual(len(moves[0].destination.name), 175)
        manifest = org.apply(self.root, moves)
        self.assertEqual(org.restore(self.root, manifest), 1)

    def test_keep_going_continues_after_a_failed_book(self):
        bad = epub(self.root / "Series/a.epub", title="Bad")
        good = epub(self.root / "Series/b.epub", title="Good")
        moves = org.plan(self.root)
        original_unlink = Path.unlink

        def fail_unlink(path, *args, **kwargs):
            if path == bad:
                raise PermissionError("simulated locked source")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_unlink):
            manifest = org.apply(self.root, moves, keep_going=True)
        self.assertTrue(bad.exists())
        self.assertFalse(good.exists())
        failed = org.failed_entries(manifest)
        self.assertEqual([e["source"] for e in failed], ["Series/a.epub"])
        self.assertEqual(org.restore(self.root, manifest), 1)

    def test_cli_keep_going_reports_failure_exit_code(self):
        bad = epub(self.root / "Series/a.epub")
        original_unlink = Path.unlink

        def fail_unlink(path, *args, **kwargs):
            if path == bad:
                raise PermissionError("locked")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_unlink):
            self.assertEqual(main(["--root", str(self.root), "--apply", "--keep-going"]), 1)
            self.assertEqual(main(["--root", str(self.root), "--apply"]), 1)
        with self.assertRaises(SystemExit):
            main(["--root", str(self.root), "--keep-going"])

    def test_goodreads_csv_validation(self):
        epub(self.root / "book.epub")
        self.assertEqual(org.validate_goodreads_csv(org.export_csv(self.root)), [])
        bad = self.root / "bad.csv"
        bad.write_text("Title,Author,ISBN13\n,A,123\nT,A,123\nT,A,9780306406157\n", encoding="utf-8-sig")
        problems = org.validate_goodreads_csv(bad)
        self.assertEqual(len(problems), 2)
        self.assertIn("empty Title", problems[0])
        self.assertIn("13 digits", problems[1])
        bad.write_text("Name,Author\nT,A\n", encoding="utf-8-sig")
        self.assertIn("Unexpected header", org.validate_goodreads_csv(bad)[0])
