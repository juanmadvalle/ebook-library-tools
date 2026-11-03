"""Plan first; keep backups and never overwrite a destination."""

import csv
import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .metadata import Metadata, read_metadata
from .naming import canonical_stem
from .records import checksum, encode_record, entries, no_links, read_record, relative_file

STATE_DIR = ".ebook-organizer"


@dataclass(frozen=True)
class Move:
    source: Path
    destination: Path
    digest: str
    metadata: Metadata


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def checked_root(root: Path) -> Path:
    no_links(root.expanduser().absolute())
    root = root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Library root must be a directory")
    return root


def is_link(path: Path) -> bool:
    # Windows junctions expose FILE_ATTRIBUTE_REPARSE_POINT too.
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def discover(root: Path):
    for directory, folders, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        folders[:] = sorted(name for name in folders
                            if name != STATE_DIR and not is_link(parent / name))
        for name in sorted(files):
            path = parent / name
            if path.suffix.lower() == ".epub" and not is_link(path):
                yield path


def plan(root: Path, mode: str = "last") -> list[Move]:
    root = checked_root(root)
    if mode not in ("last", "concat"):
        raise ValueError("Series mode must be last or concat")
    # Reserve ALL existing root entries, including folders and case variants.
    reserved = {entry.name.casefold() for entry in root.iterdir()}
    moves = []
    for source in discover(root):
        # Existing root-level books are intentionally stable. No filename guessing.
        if source.parent == root:
            continue
        metadata = read_metadata(source)  # Fail before writing if any EPUB is unreadable.
        base = canonical_stem(source, root, metadata, mode)
        stem, number = base, 1
        while (stem + ".epub").casefold() in reserved:
            stem = f"{base}_{number}"
            number += 1
        reserved.add((stem + ".epub").casefold())
        moves.append(Move(source, root / (stem + ".epub"), digest(source), metadata))
    return moves


def copy_exclusive(source: Path, destination: Path, expected: str) -> None:
    """Only clean up files created here; never remove an existing destination."""
    created = False
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            created = True
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if digest(destination) != expected or digest(source) != expected:
            raise ValueError(f"File changed or copy verification failed: {source.name}")
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def write_journal(path: Path, data: dict) -> None:
    text = encode_record(data)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_moves(root: Path, moves: list[Move]) -> None:
    sources, destinations = set(), set()
    existing = {p.name.casefold() for p in root.iterdir()}
    for move in moves:
        source = relative_file(root, move.source.relative_to(root).as_posix())
        destination = relative_file(root, move.destination.relative_to(root).as_posix(), single=True)
        source_key = str(source).casefold()
        target_key = destination.name.casefold()
        if (source.parent == root or source.relative_to(root).parts[0].casefold() == STATE_DIR
                or source.suffix.lower() != ".epub" or destination.suffix.lower() != ".epub"
                or source_key in sources or target_key in destinations):
            raise ValueError("Invalid or duplicate move")
        if not source.is_file() or digest(source) != checksum(move.digest) or target_key in existing:
            raise ValueError(f"Plan is stale: {source.name}")
        sources.add(source_key)
        destinations.add(target_key)


def save_plan(root: Path, moves: list[Move], target: Path) -> Path:
    root = checked_root(root)
    validate_moves(root, moves)
    data = {"version": 1, "kind": "ebook-plan", "root": str(root), "entries": [
        {"source": m.source.relative_to(root).as_posix(), "destination": m.destination.name,
         "sha256": m.digest} for m in moves]}
    no_links(target.absolute())
    text = encode_record(data)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    return target


def load_plan(root: Path, target: Path) -> list[Move]:
    root = checked_root(root)
    no_links(target.absolute())
    data = read_record(target)
    if data.get("kind") != "ebook-plan" or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Unsupported plan")
    if data.get("root") != str(root):
        raise ValueError("Plan belongs to a different library")
    moves = [Move(relative_file(root, e["source"]),
                  relative_file(root, e["destination"], single=True),
                  checksum(e["sha256"]), Metadata()) for e in entries(data)]
    validate_moves(root, moves)
    return moves


def apply(root: Path, moves: list[Move], keep_going: bool = False) -> Path | None:
    """Apply moves; with keep_going, record per-book failures and continue."""
    root = checked_root(root)
    if not moves:
        return None
    validate_moves(root, moves)
    state = root / STATE_DIR
    no_links(state)
    state.mkdir(exist_ok=True)
    transaction = state / uuid4().hex
    transaction.mkdir()
    journal_path = transaction / "manifest.json"
    data = {"version": 2, "entries": [
        {"source": m.source.relative_to(root).as_posix(), "destination": m.destination.name,
         "backup": f"{i}.epub", "sha256": m.digest, "status": "planned"}
        for i, m in enumerate(moves)]}
    write_journal(journal_path, data)
    for index, move in enumerate(moves):
        entry = data["entries"][index]
        try:
            backup = transaction / f"{index}.epub"
            copy_exclusive(move.source, backup, move.digest)
            entry["status"] = "backed_up"
            write_journal(journal_path, data)
            copy_exclusive(move.source, move.destination, move.digest)
            entry["status"] = "copied"
            write_journal(journal_path, data)
            # Recheck before deleting. Backups also survive interruption or later failure.
            if digest(move.source) != move.digest:
                raise ValueError("Source changed; source and backup retained")
            move.source.unlink()
            entry["status"] = "moved"
            write_journal(journal_path, data)
        except Exception as exc:
            if not keep_going:
                raise
            # Keep the last reached step so --status diagnoses real file state.
            entry["error"] = str(exc)
            write_journal(journal_path, data)
    return journal_path


def failed_entries(manifest: Path) -> list[dict]:
    """Entries recorded with an error by a keep_going run."""
    return [e for e in entries(read_record(manifest)) if "error" in e]


def recovery_entries(root: Path, manifest: Path) -> list[dict]:
    root = checked_root(root)
    manifest = manifest.absolute()
    no_links(manifest)
    state = root / STATE_DIR
    if manifest.parent.parent != state or manifest.name != "manifest.json":
        raise ValueError("Manifest must be inside a library transaction directory")
    data = read_record(manifest)
    if type(data.get("version")) is not int or data["version"] not in (1, 2):
        raise ValueError("Unsupported manifest version")
    result, sources, destinations, backups = [], set(), set(), set()
    for entry in entries(data):
        source = relative_file(root, entry["source"])
        destination = relative_file(root, entry["destination"], single=True)
        backup = relative_file(manifest.parent, entry["backup"], single=True)
        expected = checksum(entry["sha256"])
        if (source.parent == root or source.relative_to(root).parts[0].casefold() == STATE_DIR
                or any(p.suffix.lower() != ".epub" for p in (source, destination, backup))
                or entry.get("status") not in ("planned", "backed_up", "copied", "moved")):
            raise ValueError("Invalid recovery entry")
        for path, seen in ((source, sources), (destination, destinations), (backup, backups)):
            key = str(path).casefold()
            if key in seen:
                raise ValueError("Duplicate recovery path")
            seen.add(key)
        def state_of(path):
            if not path.exists():
                return "missing"
            return "verified" if path.is_file() and digest(path) == expected else "conflict"
        result.append({"source": source, "destination": destination, "backup": backup,
                       "sha256": expected, "recorded": entry["status"],
                       "original": state_of(source), "copy": state_of(destination),
                       "backup_state": state_of(backup)})
    return result


def inspect_recovery(root: Path, manifest: Path) -> list[dict]:
    """Read-only diagnosis uses actual hashes, not just the last journal status."""
    result = recovery_entries(root, manifest)
    for entry in result:
        if entry["original"] == "conflict":
            advice = "blocked: original path contains different content"
        elif entry["original"] == "verified":
            advice = "original intact; no restoration needed"
        elif entry["backup_state"] == "verified":
            advice = "recoverable: use --restore to recreate the original"
        else:
            advice = "blocked: original missing and no verified backup"
        entry["advice"] = advice
    return result


def restore(root: Path, manifest: Path) -> int:
    # Preflight every entry before restoring any file.
    records = recovery_entries(root, manifest)
    for entry in records:
        if entry["original"] == "conflict":
            raise FileExistsError("Original path contains different content")
        if entry["backup_state"] != "verified" and not (
                entry["recorded"] == "planned" and entry["original"] == "verified"):
            raise ValueError("Backup integrity check failed")
    restored = 0
    for entry in reversed(records):
        source, backup = entry["source"], entry["backup"]
        if entry["original"] == "missing":
            no_links(source)
            no_links(backup)
            source.parent.mkdir(parents=True, exist_ok=True)
            copy_exclusive(backup, source, entry["sha256"])
            restored += 1
    # Keep organized destinations too: restoration must not delete later user edits.
    return restored


GOODREADS_COLUMNS = ["Title", "Author", "ISBN13"]


def validate_goodreads_csv(path: Path) -> list[str]:
    """Return problems against the Goodreads import columns; empty means valid."""
    problems = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != GOODREADS_COLUMNS:
            return [f"Unexpected header: {reader.fieldnames}"]
        for number, row in enumerate(reader, start=2):
            if None in row or None in row.values():
                problems.append(f"line {number}: wrong number of columns")
            elif not row["Title"].strip():
                problems.append(f"line {number}: empty Title")
            elif row["ISBN13"] and not (row["ISBN13"].isascii() and row["ISBN13"].isdigit()
                                        and len(row["ISBN13"]) == 13):
                problems.append(f"line {number}: ISBN13 must be 13 digits")
    return problems


def spreadsheet_cell(value: str) -> str:
    # Quote leading formula characters, including after whitespace/control chars.
    stripped = value.lstrip(" \t\r\n\v\f\ufeff")
    return "'" + value if stripped.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


def export_csv(root: Path, *, raw: bool = False) -> Path:
    root = checked_root(root)
    rows = []
    for path in discover(root):
        metadata = read_metadata(path)
        row = {"Title": metadata.title or path.stem, "Author": metadata.author, "ISBN13": metadata.isbn}
        rows.append(row if raw else {key: spreadsheet_cell(value) for key, value in row.items()})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=GOODREADS_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    # A unique export preserves previous exports even on repeated runs.
    target = root / f"goodreads_import_{uuid4().hex}.csv"
    with target.open("x", newline="", encoding="utf-8-sig") as stream:
        stream.write(buffer.getvalue())
    problems = validate_goodreads_csv(target)
    if problems:
        raise ValueError(f"Export {target.name} kept but invalid: {'; '.join(problems[:5])}")
    return target
