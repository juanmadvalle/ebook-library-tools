"""Regression checks use synthetic EPUBs, never a personal library."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from ebook_library_tools.cli import main
from ebook_library_tools.metadata import read_metadata
from ebook_library_tools.naming import sanitize
from ebook_library_tools.organizer import apply, copy_exclusive, digest, export_csv, plan, restore


def epub(path, author="Author", title="Title"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
        archive.writestr("book.opf", f'<package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>{author}</dc:creator><dc:title>{title}</dc:title></metadata></package>')
    return path


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_preview_is_read_only(self):
        source = epub(self.root / "Series/book.epub")
        before = digest(source)
        self.assertEqual(main(["--root", str(self.root)]), 0)
        self.assertEqual(digest(source), before)
        self.assertFalse((self.root / ".ebook-organizer").exists())

    def test_case_insensitive_reservations(self):
        (self.root / "author-series-title.EPUB").write_bytes(b"existing root file")
        epub(self.root / "Series/a.epub")
        epub(self.root / "Series/b.epub")
        moves = plan(self.root)
        self.assertEqual([m.destination.name for m in moves],
                         ["Author-Series-Title_1.epub", "Author-Series-Title_2.epub"])
        apply(self.root, moves)
        self.assertEqual((self.root / "author-series-title.EPUB").read_bytes(), b"existing root file")

    def test_apply_restore_and_repeat(self):
        source = epub(self.root / "Series/book.epub", "Jean-Paul", "A-B")
        before = source.read_bytes()
        moves = plan(self.root)
        manifest = apply(self.root, moves)
        self.assertFalse(source.exists())
        self.assertEqual(moves[0].destination.read_bytes(), before)
        self.assertEqual(plan(self.root), [])
        self.assertEqual(restore(self.root, manifest), 1)
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue(moves[0].destination.exists())
        self.assertEqual(restore(self.root, manifest), 0)

    def test_restore_rejects_conflict(self):
        source = epub(self.root / "Series/book.epub")
        manifest = apply(self.root, plan(self.root))
        source.write_bytes(b"new content")
        with self.assertRaises(FileExistsError):
            restore(self.root, manifest)
        self.assertEqual(source.read_bytes(), b"new content")

    def test_existing_destination_not_deleted(self):
        source = epub(self.root / "Series/book.epub")
        destination = self.root / "existing.epub"
        destination.write_bytes(b"keep me")
        with self.assertRaises(FileExistsError):
            copy_exclusive(source, destination, digest(source))
        self.assertEqual(destination.read_bytes(), b"keep me")
        self.assertTrue(source.exists())

    def test_copy_failure_keeps_original_and_backup(self):
        source = epub(self.root / "Series/book.epub")
        moves = plan(self.root)
        real_copy = copy_exclusive

        def fail_destination(src, dst, checksum):
            if dst == moves[0].destination:
                raise OSError("simulated full disk")
            return real_copy(src, dst, checksum)

        with patch("ebook_library_tools.organizer.copy_exclusive", side_effect=fail_destination):
            with self.assertRaises(OSError):
                apply(self.root, moves)
        manifest = next((self.root / ".ebook-organizer").glob("*/manifest.json"))
        entry = json.loads(manifest.read_text())["entries"][0]
        self.assertEqual(digest(manifest.parent / entry["backup"]), digest(source))
        self.assertTrue(source.exists())

    def test_changed_source_aborts_before_writing(self):
        source = epub(self.root / "Series/book.epub")
        moves = plan(self.root)
        source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            apply(self.root, moves)
        self.assertFalse((self.root / ".ebook-organizer").exists())

    def test_unlink_failure_retains_source_destination_and_backup(self):
        source = epub(self.root / "Series/book.epub")
        moves = plan(self.root)
        original_unlink = Path.unlink

        def fail_unlink(path, *args, **kwargs):
            if path == source:
                raise PermissionError("simulated locked source")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_unlink):
            with self.assertRaises(PermissionError):
                apply(self.root, moves)
        self.assertEqual(source.read_bytes(), moves[0].destination.read_bytes())
        manifest = next((self.root / ".ebook-organizer").glob("*/manifest.json"))
        self.assertEqual(restore(self.root, manifest), 0)

    def test_oversized_and_entity_metadata_rejected(self):
        source = epub(self.root / "Series/book.epub")
        with ZipFile(source, "w") as archive:
            archive.writestr("META-INF/container.xml", b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            read_metadata(source)
        with ZipFile(source, "w") as archive:
            archive.writestr("META-INF/container.xml", '<!DOCTYPE container [<!ENTITY x "test">]><container/>')
        with self.assertRaises(ValueError):
            read_metadata(source)

    def test_isbn13_validation(self):
        source = epub(self.root / "book.epub")
        with ZipFile(source, "w") as archive:
            archive.writestr("META-INF/container.xml", '<container><rootfile full-path="isbn.opf"/></container>')
            archive.writestr("isbn.opf", '<package><metadata><identifier scheme="ISBN">978-0-306-40615-7</identifier></metadata></package>')
        self.assertEqual(read_metadata(source).isbn, "9780306406157")

    def test_invalid_epub_aborts_plan(self):
        source = self.root / "Series/bad.epub"
        source.parent.mkdir()
        source.write_bytes(b"not a ZIP")
        self.assertEqual(main(["--root", str(self.root), "--apply"]), 1)
        self.assertTrue(source.exists())
        self.assertFalse((self.root / ".ebook-organizer").exists())

    def test_uppercase_extension_and_existing_hyphens(self):
        root_book = epub(self.root / "An-existing-title.epub")
        epub(self.root / "Series/book.EPUB")
        self.assertEqual(len(plan(self.root)), 1)
        self.assertTrue(root_book.exists())

    def test_exports_do_not_overwrite(self):
        epub(self.root / "book.epub")
        first = export_csv(self.root)
        second = export_csv(self.root)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_sanitization_and_metadata(self):
        self.assertEqual(sanitize("CON"), "_CON")
        self.assertEqual(sanitize("Invierno &#237;"), "Invierno_i")
        self.assertEqual(read_metadata(epub(self.root / "book.epub")).author, "Author")


if __name__ == "__main__":
    unittest.main()
