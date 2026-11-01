"""Portable filenames; metadata is not inferred from ambiguous hyphens."""

import html
import re
import unicodedata
from pathlib import Path

from .metadata import Metadata

RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
RECOVERABLE = {161, 191, 193, 201, 205, 209, 211, 218, 220,
               225, 233, 237, 241, 243, 250, 252}


def sanitize(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"_(\d{2,3})_", lambda m: chr(int(m[1]))
                  if int(m[1]) in RECOVERABLE else m[0], text)
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"_+", "_", text).strip("_. ")
    if not text:
        return "Unknown"
    if text.split(".")[0].upper() in RESERVED:
        text = "_" + text
    return text


def canonical_stem(path: Path, root: Path, metadata: Metadata, mode: str) -> str:
    folders = path.relative_to(root).parts[:-1]
    author = metadata.author or "Unknown author"
    title = metadata.title or path.stem.replace("_", " ")
    series = folders[-1:] if mode == "last" else folders
    blocks = [author, *series, title]
    # Keep enough room for a numeric suffix and the extension on common filesystems.
    return "-".join(sanitize(block) for block in blocks)[:170].rstrip(". ")
