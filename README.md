# EPUB library tools

Organize EPUBs from subfolders into a library root using embedded author/title metadata and the parent folder as a series label. Filenames use `Author-Series-Title.epub`, underscores for spaces, and accent normalization. Multiple authors are preserved; author order is not guessed from commas.

Private repository candidate. No books, reading logs, exports, or compiled executables are included. Python 3.10+; runtime uses only the standard library.

## Run from source

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD/src"
python -m ebook_library_tools --root 'D:/Books'
python -m ebook_library_tools --root 'D:/Books' --apply
python -m ebook_library_tools --root 'D:/Books' --export-csv
python -m ebook_library_tools --root 'D:/Books' --restore 'D:/Books/.ebook-organizer/TRANSACTION/manifest.json'
python -m unittest discover -s tests -v
```

Alternatively, `python -m pip install -e .` installs the `ebook-organizer` command. Building/installing may require downloading setuptools; running from source does not.

## Safety and behavior

- Default execution is a read-only preview. An explicit root is required.
- All files are planned before modifications. Unreadable metadata aborts planning.
- Root-level books remain unchanged, including names from the older organizer. This avoids ambiguous author/title splitting and makes repeated organization stable.
- Both `.epub` and `.EPUB` are discovered. Symbolic links and Windows reparse points are skipped during discovery.
- Destinations reserve all existing root names, using case-insensitive comparisons. Existing files are never intentionally overwritten; destination creation is exclusive.
- Each source is backed up under `.ebook-organizer/TRANSACTION/` and verified with SHA-256. The journal is saved before the original is removed. Backups consume approximately the size of processed books and remain until you manually remove them after review.
- Application stops on the first error. Completed earlier moves remain; this is not an all-or-nothing transaction. Retained backups and manifests support recovery. An interrupted backup before it enters the manifest can leave an extra backup file; the original has not yet been removed.
- Restore recreates missing originals, refuses conflicting content, and keeps organized destinations and backups. It is a recovery operation, not a destructive rollback.
- Empty directories are retained. CSV export is separate and writes a unique file instead of overwriting previous exports. Goodreads acceptance of the CSV has not been tested against the service.
- The ISBN13 column includes only recognized, valid ISBN-13 identifiers; ISBN-10 conversion is not performed.
- `--nested-saga concat` includes the complete relative folder hierarchy in the filename.

Keep the library idle during apply or restore; concurrent writers and malicious local filesystem changes are outside the supported use case. Back up your library independently. Copying preserves bytes, not all filesystem metadata. Do not treat the generated CSV as a spreadsheet formula-safe export of untrusted metadata.

## Changes from the recovered script

The old executable is not reused. The old source is preserved outside this repository in the recovery collection. This rewrite removes automatic root renaming, blanket empty-folder deletion, silent copy cleanup, automatic CSV replacement, and double-click mutation. Naming now prefers the embedded title, preserving its capitalization; existing root books are deliberately not migrated.

No executable build is distributed. Reproducible executable packaging and a public license remain future decisions.
