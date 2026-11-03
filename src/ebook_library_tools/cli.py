"""Command-line entry point. Preview is the default."""

import argparse
import sys
from pathlib import Path

from .organizer import (apply, checked_root, export_csv, failed_entries, inspect_recovery,
                        load_plan, plan, restore, save_plan)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Preview and safely organize EPUB files.")
    parser.add_argument("--root", required=True, type=Path, help="Library directory")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="Apply the previewed naming rules")
    action.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    action.add_argument("--restore", type=Path, metavar="MANIFEST", help="Restore originals from backups")
    action.add_argument("--export-csv", action="store_true", help="Write a new metadata CSV only")
    action.add_argument("--save-plan", type=Path, metavar="JSON", help="Save the exact preview without moving books")
    action.add_argument("--apply-plan", type=Path, metavar="JSON", help="Validate and execute a saved plan")
    action.add_argument("--status", type=Path, metavar="MANIFEST", help="Diagnose a transaction without changes")
    parser.add_argument("--raw-csv", action="store_true", help="With --export-csv only: preserve formula-like metadata")
    parser.add_argument("--keep-going", action="store_true",
                        help="With --apply/--apply-plan: continue after a per-book error and report failures")
    parser.add_argument("--nested-saga", choices=("last", "concat"), default="last")
    args = parser.parse_args(argv)
    if args.raw_csv and not args.export_csv:
        parser.error("--raw-csv requires --export-csv")
    if args.keep_going and not (args.apply or args.apply_plan):
        parser.error("--keep-going requires --apply or --apply-plan")
    status = 0
    try:
        root = checked_root(args.root)
        if args.restore:
            print(f"Restored {restore(root, args.restore)} originals; organized copies retained.")
        elif args.status:
            for item in inspect_recovery(root, args.status):
                print(f"{item['source'].relative_to(root)}: {item['advice']}; "
                      f"recorded={item['recorded']}, original={item['original']}, "
                      f"destination={item['copy']}, backup={item['backup_state']}")
        elif args.export_csv:
            print(f"Export: {export_csv(root, raw=args.raw_csv)}")
        else:
            moves = load_plan(root, args.apply_plan) if args.apply_plan else plan(root, args.nested_saga)
            for move in moves:
                print(f"{move.source.relative_to(root)} -> {move.destination.name}")
            print(f"{len(moves)} files to organize; root-level books remain unchanged.")
            if args.save_plan:
                print(f"Saved plan: {save_plan(root, moves, args.save_plan)}")
            elif args.apply or args.apply_plan:
                manifest = apply(root, moves, keep_going=args.keep_going)
                if manifest:
                    print(f"Recovery manifest: {manifest}")
                    for entry in failed_entries(manifest):
                        print(f"FAILED {entry['source']}: {entry['error']}", file=sys.stderr)
                        status = 1
            else:
                print("Preview only. Use --apply to make changes.")
        return status
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("If an apply was interrupted, use --status with .ebook-organizer/TRANSACTION/manifest.json; backups are retained.",
              file=sys.stderr)
        return 1
