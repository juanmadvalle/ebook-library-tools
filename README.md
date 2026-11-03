# EPUB library tools

Organize EPUBs from subfolders into a library root using embedded author/title metadata and the parent folder as a series label. Filenames use `Author-Series-Title.epub`, underscores for spaces, and accent normalization. Multiple authors are preserved; author order is not guessed from commas.

No books, reading logs, exports, or compiled executables are included. Python 3.10+; runtime uses only the standard library.

## Run from source

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD/src"
python -m ebook_library_tools --root 'D:/Books'
python -m ebook_library_tools --root 'D:/Books' --save-plan './ebook-plan-review.json'
python -m ebook_library_tools --root 'D:/Books' --apply-plan './ebook-plan-review.json'
python -m ebook_library_tools --root 'D:/Books' --apply-plan './ebook-plan-review.json' --keep-going
python -m ebook_library_tools --root 'D:/Books' --export-csv
python -m ebook_library_tools --root 'D:/Books' --status 'D:/Books/.ebook-organizer/TRANSACTION/manifest.json'
python -m ebook_library_tools --root 'D:/Books' --restore 'D:/Books/.ebook-organizer/TRANSACTION/manifest.json'
python -m unittest discover -s tests -v
```

Alternatively, `python -m pip install -e .` installs the `ebook-organizer` command. Building/installing may require downloading setuptools; running from source does not.

## Safety and behavior

- Default execution is a read-only preview. An explicit root is required.
- All files are planned before modifications. Unreadable metadata aborts planning.
- Saved plans bind exact source/destination pairs and SHA-256 checksums to one library root. Application rejects changed sources and occupied destinations before moving anything. New books added after saving are not included. `--apply` still computes and applies a fresh plan; use `--apply-plan` to execute what you reviewed.
- Root-level books remain unchanged, including names from the older organizer. This avoids ambiguous author/title splitting and makes repeated organization stable.
- Both `.epub` and `.EPUB` are discovered. Symbolic links and Windows reparse points are skipped during discovery.
- Destinations reserve all existing root names, using case-insensitive comparisons. Existing files are never intentionally overwritten; destination creation is exclusive.
- Each source is backed up under `.ebook-organizer/TRANSACTION/` and verified with SHA-256. The journal is saved before the original is removed. Backups consume approximately the size of processed books and remain until you manually remove them after review.
- Application stops on the first error by default. With `--keep-going` (requires `--apply` or `--apply-plan`) a failing book is recorded with its error in the journal, the remaining books are still processed, failures are printed and the exit code is 1. Either way, completed earlier moves remain; this is not an all-or-nothing transaction. The complete plan is recorded before copying starts. Retained backups and manifests support recovery; `--status` diagnoses actual file content after interruptions.
- Restore recreates missing originals, refuses conflicting content, and keeps organized destinations and backups. It is a recovery operation, not a destructive rollback.
- Empty directories are retained. CSV export is separate and writes a unique file instead of overwriting previous exports. The export is checked after writing against the expected columns (`Title,Author,ISBN13`), a nonempty title and 13-digit ISBNs; an invalid file is kept and reported as an error. Goodreads acceptance of the CSV has not been tested against the service.
- The ISBN13 column includes only recognized, valid ISBN-13 identifiers; ISBN-10 conversion is not performed.
- `--nested-saga concat` includes the complete relative folder hierarchy in the filename.

Keep the library idle during apply or restore; concurrent writers and malicious local filesystem changes are outside the supported use case. Back up your library independently. Copying preserves bytes, not all filesystem metadata. CSV export protects formula-like cells by default; `--raw-csv` explicitly disables that protection for consumers requiring exact metadata.

See the [synthetic walkthrough and recovery guide](docs/RECOVERY.md) and [changelog](CHANGELOG.md). JSON records are bounded to 8 MiB. Recovery validates all entries before writing and rejects unsafe paths, linked ancestors, duplicate paths, conflicting originals and corrupt required backups.

## Changes from the recovered script

The old executable is not reused. The old source is preserved outside this repository in the recovery collection. This rewrite removes automatic root renaming, blanket empty-folder deletion, silent copy cleanup, automatic CSV replacement, and double-click mutation. Naming now prefers the embedded title, preserving its capitalization; existing root books are deliberately not migrated.

No executable build is distributed. Reproducible executable packaging remains a future decision.

## License

Licensed under the [MIT License](LICENSE).
