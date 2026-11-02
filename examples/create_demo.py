"""Create two synthetic metadata fixtures in a NEW directory, never a real library."""
import argparse
from pathlib import Path
from zipfile import ZipFile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
args.root.mkdir(parents=True, exist_ok=False)
for series in ("Series One", "Series Two"):
    folder = args.root / series
    folder.mkdir()
    with ZipFile(folder / "sample.epub", "w") as archive:
        archive.writestr("META-INF/container.xml", '<container><rootfile full-path="book.opf"/></container>')
        archive.writestr("book.opf", '<package><metadata><creator>Example Author</creator><title>Example Book</title></metadata></package>')
print(f"Created two synthetic metadata fixtures in {args.root}. These are not complete readable EPUBs.")
