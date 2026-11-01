"""Command-line entry point. Preview is the default."""

import argparse
import sys
from pathlib import Path

from .organizer import apply, checked_root, export_csv, plan, restore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Preview and safely organize EPUB files.")
    parser.add_argument("--root", required=True, type=Path, help="Library directory")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="Apply the previewed naming rules")
    action.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    action.add_argument("--restore", type=Path, metavar="MANIFEST", help="Restore originals from backups")
    action.add_argument("--export-csv", action="store_true", help="Write a new metadata CSV only")
    parser.add_argument("--nested-saga", choices=("last", "concat"), default="last")
    args = parser.parse_args(argv)
    try:
        root = checked_root(args.root)
        if args.restore:
            print(f"Restored {restore(root, args.restore)} originals; organized copies retained.")
        elif args.export_csv:
            print(f"Export: {export_csv(root)}")
        else:
            moves = plan(root, args.nested_saga)
            for move in moves:
                print(f"{move.source.relative_to(root)} -> {move.destination.name}")
            print(f"{len(moves)} files to organize; root-level books remain unchanged.")
            if args.apply:
                manifest = apply(root, moves)
                if manifest:
                    print(f"Recovery manifest: {manifest}")
            else:
                print("Preview only. Use --apply to make changes.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("If an apply was interrupted, inspect .ebook-organizer/*/manifest.json; backups are retained.",
              file=sys.stderr)
        return 1
