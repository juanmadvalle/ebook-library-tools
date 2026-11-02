# Recovery and reproducible walkthrough

Run from the repository root, using a NEW demo directory:

```powershell
$env:PYTHONPATH = "$PWD/src"
python examples/create_demo.py --root ./demo-library
python -m ebook_library_tools --root ./demo-library --save-plan ./ebook-plan-demo.json
Get-Content ./ebook-plan-demo.json
python -m ebook_library_tools --root ./demo-library --apply-plan ./ebook-plan-demo.json
```

Expected: two planned moves, then two files at the library root named
`Example_Author-Series_One-Example_Book.epub` and
`Example_Author-Series_Two-Example_Book.epub`. Each original has a verified backup.
The plan stores the absolute library root and relative source paths. Treat it as
private metadata. `ebook-plan*.json` is ignored by Git. Choose a new plan filename
for another preview; existing plans are never overwritten. Plans are not signed:
review their contents and keep them in a trusted location.

Use the manifest path printed by the apply command:

```powershell
python -m ebook_library_tools --root ./demo-library --status ./demo-library/.ebook-organizer/TRANSACTION/manifest.json
python -m ebook_library_tools --root ./demo-library --restore ./demo-library/.ebook-organizer/TRANSACTION/manifest.json
```

Replace `TRANSACTION` with the actual directory name. Status is read-only and
reports the current hashes of the original, destination and backup, plus the last
recorded stage. After a normal apply, the original is missing and its backup and
destination are verified. Restore recreates originals and keeps organized copies.

If an execution stops:

1. Stop other tools that could change the library. Do not blindly reapply the plan.
2. Run `--status` for the transaction and inspect all reported conflicts.
3. `--restore` checks every entry before writing. It refuses conflicting original
   paths and missing/corrupt required backups. A still-planned entry whose original
   is intact needs no backup to remain recoverable.
4. If blocked, preserve all files and use an independent backup or resolve the
   conflict manually. Never delete the state directory as a troubleshooting step.

Version 1 manifests remain readable. Version 2 records the complete plan before
copying starts, so not-yet-started operations appear in status. Failure before the
first journal is saved leaves the originals unchanged; an empty transaction
directory can remain. Filesystem/hardware power-loss durability is not guaranteed.
External concurrent changes and hostile local writers remain outside scope.

CSV export prefixes formula-like metadata with an apostrophe by default. This is
a conservative protection for common spreadsheet imports, not a guarantee for
every application or after saving/reopening edited data. `--export-csv --raw-csv`
preserves original metadata for non-spreadsheet consumers; use it only knowingly.
