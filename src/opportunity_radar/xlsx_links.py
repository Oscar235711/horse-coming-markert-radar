"""Native OOXML external hyperlinks for workbooks emitted by artifact-tool.

artifact-tool currently serializes Excel's ``HYPERLINK`` formula as an error
cell.  This small post-export adapter writes the relationship Excel and WPS
expect instead, without adding another runtime dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
HYPERLINK_REL_TYPE = f"{DOCUMENT_REL_NS}/hyperlink"


def inject_external_hyperlinks(
    workbook_path: Path,
    *,
    sheet_name: str,
    links: Mapping[str, str],
) -> None:
    """Add real external hyperlink relationships to a worksheet in an XLSX.

    ``links`` maps Excel cell references such as ``H4`` to HTTPS evidence
    URLs.  Existing managed links for those cells are replaced, so re-export
    is idempotent.
    """
    normalized = {str(cell).upper(): str(url).strip() for cell, url in links.items() if str(url).strip()}
    if not normalized:
        return
    for cell, url in normalized.items():
        if not _is_external_http_url(url):
            raise ValueError(f"External hyperlink for {cell} must be an HTTP(S) URL")

    workbook_path = Path(workbook_path)
    if not workbook_path.is_file():
        raise FileNotFoundError(workbook_path)

    with ZipFile(workbook_path) as source:
        entries = {entry.filename: source.read(entry.filename) for entry in source.infolist()}

    sheet_path = _sheet_part_path(entries, sheet_name)
    rel_path = str(PurePosixPath(sheet_path).parent / "_rels" / f"{PurePosixPath(sheet_path).name}.rels")
    sheet = ET.fromstring(entries[sheet_path])
    relationships = ET.fromstring(entries[rel_path]) if rel_path in entries else ET.Element(_q(PACKAGE_REL_NS, "Relationships"))

    _remove_managed_links(sheet, relationships, set(normalized))
    hyperlinks = _hyperlinks_element(sheet)
    existing_ids = {item.attrib.get("Id", "") for item in relationships.findall(_q(PACKAGE_REL_NS, "Relationship"))}
    for cell, url in normalized.items():
        _set_display_value(sheet, cell, "打开证据")
        relationship_id = _next_relationship_id(existing_ids)
        existing_ids.add(relationship_id)
        ET.SubElement(
            relationships,
            _q(PACKAGE_REL_NS, "Relationship"),
            {"Id": relationship_id, "Type": HYPERLINK_REL_TYPE, "Target": url, "TargetMode": "External"},
        )
        ET.SubElement(hyperlinks, _q(MAIN_NS, "hyperlink"), {"ref": cell, _q(DOCUMENT_REL_NS, "id"): relationship_id})

    entries[sheet_path] = _xml_bytes(sheet)
    entries[rel_path] = _xml_bytes(relationships)
    _rewrite_archive(workbook_path, entries)
    _verify_external_hyperlinks(workbook_path, sheet_name=sheet_name, links=normalized)


def _q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def _is_external_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sheet_part_path(entries: Mapping[str, bytes], sheet_name: str) -> str:
    workbook = ET.fromstring(entries["xl/workbook.xml"])
    sheet = next(
        (item for item in workbook.findall(f".//{_q(MAIN_NS, 'sheet')}") if item.attrib.get("name") == sheet_name),
        None,
    )
    if sheet is None:
        raise KeyError(f"Worksheet not found: {sheet_name}")
    relationship_id = sheet.attrib.get(_q(DOCUMENT_REL_NS, "id"))
    relationships = ET.fromstring(entries["xl/_rels/workbook.xml.rels"])
    relationship = next(
        (item for item in relationships.findall(_q(PACKAGE_REL_NS, "Relationship")) if item.attrib.get("Id") == relationship_id),
        None,
    )
    if relationship is None:
        raise KeyError(f"Workbook relationship not found: {relationship_id}")
    target = str(relationship.attrib.get("Target", ""))
    if target.startswith("/"):
        path = target.lstrip("/")
    else:
        path = str(PurePosixPath("xl/workbook.xml").parent / target)
    if path not in entries:
        raise KeyError(f"Worksheet XML not found: {path}")
    return path


def _remove_managed_links(sheet: ET.Element, relationships: ET.Element, cells: set[str]) -> None:
    hyperlinks = sheet.find(_q(MAIN_NS, "hyperlinks"))
    if hyperlinks is None:
        return
    for link in tuple(hyperlinks.findall(_q(MAIN_NS, "hyperlink"))):
        if link.attrib.get("ref", "").upper() not in cells:
            continue
        relationship_id = link.attrib.get(_q(DOCUMENT_REL_NS, "id"))
        hyperlinks.remove(link)
        if relationship_id:
            relation = next(
                (item for item in relationships.findall(_q(PACKAGE_REL_NS, "Relationship")) if item.attrib.get("Id") == relationship_id),
                None,
            )
            if relation is not None and relation.attrib.get("Type") == HYPERLINK_REL_TYPE:
                relationships.remove(relation)
    if not hyperlinks.findall(_q(MAIN_NS, "hyperlink")):
        sheet.remove(hyperlinks)


def _hyperlinks_element(sheet: ET.Element) -> ET.Element:
    existing = sheet.find(_q(MAIN_NS, "hyperlinks"))
    if existing is not None:
        return existing
    hyperlinks = ET.Element(_q(MAIN_NS, "hyperlinks"))
    children = list(sheet)
    sheet_data_index = next((index for index, child in enumerate(children) if child.tag == _q(MAIN_NS, "sheetData")), len(children) - 1)
    sheet.insert(sheet_data_index + 1, hyperlinks)
    return hyperlinks


def _set_display_value(sheet: ET.Element, cell_reference: str, display: str) -> None:
    cell = next(
        (item for item in sheet.findall(f".//{_q(MAIN_NS, 'c')}") if item.attrib.get("r", "").upper() == cell_reference),
        None,
    )
    if cell is None:
        raise KeyError(f"Worksheet cell not found: {cell_reference}")
    for child in tuple(cell):
        if child.tag in {_q(MAIN_NS, "f"), _q(MAIN_NS, "v"), _q(MAIN_NS, "is")}:
            cell.remove(child)
    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, _q(MAIN_NS, "is"))
    text = ET.SubElement(inline, _q(MAIN_NS, "t"))
    text.text = display


def _next_relationship_id(existing_ids: set[str]) -> str:
    index = 1
    while f"rId{index}" in existing_ids:
        index += 1
    return f"rId{index}"


def _xml_bytes(root: ET.Element) -> bytes:
    ET.register_namespace("", MAIN_NS)
    ET.register_namespace("r", DOCUMENT_REL_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rewrite_archive(workbook_path: Path, entries: Mapping[str, bytes]) -> None:
    with NamedTemporaryFile(dir=workbook_path.parent, suffix=".xlsx", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as destination:
            for name, data in entries.items():
                destination.writestr(name, data)
        temporary_path.replace(workbook_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def _verify_external_hyperlinks(workbook_path: Path, *, sheet_name: str, links: Mapping[str, str]) -> None:
    with ZipFile(workbook_path) as workbook:
        entries = {name: workbook.read(name) for name in workbook.namelist()}
    sheet_path = _sheet_part_path(entries, sheet_name)
    rel_path = str(PurePosixPath(sheet_path).parent / "_rels" / f"{PurePosixPath(sheet_path).name}.rels")
    sheet = ET.fromstring(entries[sheet_path])
    relationships = ET.fromstring(entries[rel_path])
    targets = {
        relation.attrib.get("Id"): relation.attrib.get("Target")
        for relation in relationships.findall(_q(PACKAGE_REL_NS, "Relationship"))
        if relation.attrib.get("Type") == HYPERLINK_REL_TYPE and relation.attrib.get("TargetMode") == "External"
    }
    for cell, expected_url in links.items():
        link = next(
            (item for item in sheet.findall(f".//{_q(MAIN_NS, 'hyperlink')}") if item.attrib.get("ref", "").upper() == cell),
            None,
        )
        if link is None or targets.get(link.attrib.get(_q(DOCUMENT_REL_NS, "id"))) != expected_url:
            raise ValueError(f"Workbook hyperlink verification failed for {cell}")
