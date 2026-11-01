"""Plan first; keep backups and never overwrite a destination."""

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .metadata import Metadata, read_metadata
from .naming import canonical_stem

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
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def apply(root: Path, moves: list[Move]) -> Path | None:
    root = checked_root(root)
    if not moves:
        return None
    # Validate the complete plan immediately before changing anything.
    for move in moves:
        if not move.source.resolve().is_relative_to(root) or move.destination.parent != root:
            raise ValueError("Move escapes library root")
        if any(is_link(p) for p in (move.source, *move.source.parents)
               if p == root or p.is_relative_to(root)):
            raise ValueError("Linked sources are unsupported")
        if digest(move.source) != move.digest or move.destination.exists():
            raise ValueError(f"Plan is stale: {move.source.name}")
    state = root / STATE_DIR
    if state.exists() and is_link(state):
        raise ValueError("State directory cannot be a link")
    state.mkdir(exist_ok=True)
    transaction = state / uuid4().hex
    transaction.mkdir()
    journal_path = transaction / "manifest.json"
    data = {"version": 1, "entries": []}
    write_journal(journal_path, data)
    for index, move in enumerate(moves):
        backup = transaction / f"{index}.epub"
        copy_exclusive(move.source, backup, move.digest)
        entry = {"source": str(move.source.relative_to(root)),
                 "destination": move.destination.name, "backup": backup.name,
                 "sha256": move.digest, "status": "backed_up"}
        data["entries"].append(entry)
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
    return journal_path


def restore(root: Path, manifest: Path) -> int:
    root = checked_root(root)
    manifest = manifest.resolve(strict=True)
    state = root / STATE_DIR
    if is_link(state) or not manifest.is_relative_to(state.resolve()):
        raise ValueError("Manifest must be inside this library's state directory")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("Unsupported manifest version")
    restored = 0
    for entry in reversed(data["entries"]):
        source = root / entry["source"]
        backup = manifest.parent / entry["backup"]
        if not source.resolve().is_relative_to(root) or backup.parent != manifest.parent:
            raise ValueError("Unsafe manifest path")
        if digest(backup) != entry["sha256"]:
            raise ValueError("Backup integrity check failed")
        if source.exists():
            if digest(source) != entry["sha256"]:
                raise FileExistsError(f"Original path now contains a different file: {source}")
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            copy_exclusive(backup, source, entry["sha256"])
            restored += 1
    # Keep organized destinations too: restoration must not delete later user edits.
    return restored


def export_csv(root: Path) -> Path:
    root = checked_root(root)
    rows = []
    for path in discover(root):
        metadata = read_metadata(path)
        rows.append({"Title": metadata.title or path.stem,
                     "Author": metadata.author, "ISBN13": metadata.isbn})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["Title", "Author", "ISBN13"])
    writer.writeheader()
    writer.writerows(rows)
    # A unique export preserves previous exports even on repeated runs.
    target = root / f"goodreads_import_{uuid4().hex}.csv"
    with target.open("x", newline="", encoding="utf-8-sig") as stream:
        stream.write(buffer.getvalue())
    return target
