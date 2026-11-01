"""Read bounded metadata from an EPUB without extracting archive paths."""

from dataclasses import dataclass
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

MAX_XML_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Metadata:
    author: str = ""
    title: str = ""
    isbn: str = ""


def read_xml(archive: ZipFile, name: str) -> ET.Element:
    if archive.getinfo(name).file_size > MAX_XML_BYTES:
        raise ValueError(f"Metadata is too large: {name}")
    with archive.open(name) as stream:
        content = stream.read(MAX_XML_BYTES + 1)
    if len(content) > MAX_XML_BYTES:
        raise ValueError(f"Metadata is too large: {name}")
    declarations = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise ValueError("XML declarations with entities are not supported")
    return ET.fromstring(content)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_metadata(path: Path) -> Metadata:
    with ZipFile(path) as archive:
        container = read_xml(archive, "META-INF/container.xml")
        opf_path = next(
            (node.get("full-path") for node in container.iter()
             if local_name(node.tag) == "rootfile" and node.get("full-path")),
            None,
        )
        if not opf_path:
            raise ValueError("EPUB has no package document")
        package = read_xml(archive, opf_path)
        metadata = next((n for n in package if local_name(n.tag) == "metadata"), None)
        if metadata is None:
            raise ValueError("EPUB has no metadata section")
        authors, titles, identifiers = [], [], []
        for node in metadata:
            text = "".join(node.itertext()).strip()
            name = local_name(node.tag)
            if name == "creator" and text:
                authors.append(text)
            elif name == "title" and text:
                titles.append(text)
            elif name == "identifier" and text:
                scheme = " ".join(node.attrib.values()).lower()
                if "isbn" in scheme or text.lower().startswith("urn:isbn:"):
                    candidate = re.sub(r"[\s-]", "", re.sub(r"^urn:isbn:", "", text, flags=re.I))
                    if (re.fullmatch(r"97[89]\d{10}", candidate)
                            and sum(int(n) * (1 if i % 2 == 0 else 3)
                                    for i, n in enumerate(candidate)) % 10 == 0):
                        identifiers.append(candidate)
        return Metadata(" & ".join(authors), titles[0] if titles else "",
                        identifiers[0] if identifiers else "")
