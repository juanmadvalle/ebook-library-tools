"""Bounded JSON records and portable paths, validated before filesystem writes."""

import json
import os
import re
from pathlib import Path

MAX_RECORD_BYTES = 8 * 1024 * 1024


def read_record(path: Path) -> dict:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    with path.open("rb") as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("Record exceeds 8 MiB")
    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_pairs)
    if not isinstance(data, dict):
        raise ValueError("Record must be an object")
    return data


def no_links(path: Path) -> None:
    """Check lexical ancestors, including junctions and dangling symlinks."""
    for item in (path, *path.parents):
        if os.path.lexists(item):
            stat = item.lstat()
            if item.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked paths are unsupported")


def relative_file(root: Path, value: str, *, single: bool = False) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty relative path")
    parts = value.replace("\\", "/").split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
    }
    if (single and len(parts) != 1) or any(
        part in ("", ".", "..") or part.endswith((".", " "))
        or re.search(r'[<>:"|?*\x00-\x1f]', part)
        or part.split(".")[0].upper() in reserved for part in parts
    ):
        raise ValueError("Unsafe relative path")
    path = root.joinpath(*parts)
    no_links(path)
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError("A path ancestor is not a directory")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path escapes root")
    return path


def encode_record(data: dict) -> str:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("Record exceeds 8 MiB")
    return text


def checksum(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Invalid SHA-256 checksum")
    return value


def entries(data: dict) -> list:
    result = data.get("entries")
    if not isinstance(result, list) or any(not isinstance(e, dict) for e in result):
        raise ValueError("Entries must be an array of objects")
    return result
