"""Embed the bundled Noto Sans subsets into the default docx template.

Rewrites resources/template.docx in place: replaces Arial with Noto Sans in
all XML parts and embeds the four faces as obfuscated ODTTF parts, so
documents generated from the template render identically on systems without
Noto Sans installed. Re-run after regenerating the fonts with
subset_noto_fonts.py.

Usage: uv run scripts/embed_noto_into_docx_template.py
"""

import os
import uuid
import xml.etree.ElementTree as ET
import zipfile

FAMILY = "Noto Sans"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
FONT_REL_TYPE = f"{R_NS}/font"
ODTTF_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.obfuscatedFont"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = os.path.join(SCRIPT_DIR, "..", "chgksuite", "chgksuite", "resources")
TEMPLATE = os.path.join(RESOURCE_DIR, "template.docx")
FONTS_DIR = os.path.join(RESOURCE_DIR, "fonts")

EMBED_TAGS = {
    "Regular": "embedRegular",
    "Bold": "embedBold",
    "Italic": "embedItalic",
    "BoldItalic": "embedBoldItalic",
}

for prefix, ns in (("w", W_NS), ("r", R_NS)):
    ET.register_namespace(prefix, ns)


def obfuscate_odttf(font_data, guid):
    key = uuid.UUID(guid).bytes[::-1]
    data = bytearray(font_data)
    for i in range(32):
        data[i] ^= key[i % 16]
    return bytes(data)


def build_font_table(original_xml, rel_ids):
    root = ET.fromstring(original_xml)
    for el in list(root):
        if el.get(f"{{{W_NS}}}name") == FAMILY:
            root.remove(el)
    font = ET.SubElement(root, f"{{{W_NS}}}font", {f"{{{W_NS}}}name": FAMILY})
    ET.SubElement(font, f"{{{W_NS}}}charset", {f"{{{W_NS}}}val": "00"})
    ET.SubElement(font, f"{{{W_NS}}}family", {f"{{{W_NS}}}val": "swiss"})
    ET.SubElement(font, f"{{{W_NS}}}pitch", {f"{{{W_NS}}}val": "variable"})
    for face, (rel_id, guid) in rel_ids.items():
        ET.SubElement(
            font,
            f"{{{W_NS}}}{EMBED_TAGS[face]}",
            {f"{{{R_NS}}}id": rel_id, f"{{{W_NS}}}fontKey": f"{{{guid.upper()}}}"},
        )
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_font_rels(rel_ids):
    root = ET.Element(f"{{{RELS_NS}}}Relationships")
    for index, (rel_id, _guid) in enumerate(rel_ids.values(), start=1):
        ET.SubElement(
            root,
            f"{{{RELS_NS}}}Relationship",
            {
                "Id": rel_id,
                "Type": FONT_REL_TYPE,
                "Target": f"fonts/font{index}.odttf",
            },
        )
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")


def add_odttf_content_type(original_xml):
    root = ET.fromstring(original_xml)
    for el in root:
        if el.get("Extension") == "odttf":
            return original_xml
    ET.SubElement(
        root,
        f"{{{CT_NS}}}Default",
        {"Extension": "odttf", "ContentType": ODTTF_CONTENT_TYPE},
    )
    ET.register_namespace("", CT_NS)
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")


def add_embed_setting(original_xml):
    if b"embedTrueTypeFonts" in original_xml:
        return original_xml
    root = ET.fromstring(original_xml)
    # CT_Settings is an ordered sequence; embedTrueTypeFonts belongs near the
    # top, right after zoom in this template.
    index = next(
        (i for i, el in enumerate(root) if el.tag == f"{{{W_NS}}}zoom"), -1
    )
    root.insert(index + 1, ET.Element(f"{{{W_NS}}}embedTrueTypeFonts"))
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")


def main():
    rel_ids = {}
    odttf_parts = {}
    for index, face in enumerate(EMBED_TAGS, start=1):
        path = os.path.join(FONTS_DIR, f"NotoSans-{face}.ttf")
        with open(path, "rb") as f:
            font_data = f.read()
        guid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chgksuite:{FAMILY}:{face}"))
        rel_ids[face] = (f"rIdFont{index}", guid)
        odttf_parts[f"word/fonts/font{index}.odttf"] = obfuscate_odttf(
            font_data, guid
        )

    with zipfile.ZipFile(TEMPLATE) as zin:
        parts = {name: zin.read(name) for name in zin.namelist()}

    for name in [n for n in parts if n.endswith(".xml")]:
        parts[name] = (
            parts[name]
            .replace(b"Arial Unicode MS", FAMILY.encode())
            .replace(b"Arial", FAMILY.encode())
        )

    parts["word/fontTable.xml"] = build_font_table(parts["word/fontTable.xml"], rel_ids)
    parts["word/_rels/fontTable.xml.rels"] = build_font_rels(rel_ids)
    parts["[Content_Types].xml"] = add_odttf_content_type(parts["[Content_Types].xml"])
    parts["word/settings.xml"] = add_embed_setting(parts["word/settings.xml"])
    parts.update(odttf_parts)

    with zipfile.ZipFile(TEMPLATE, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in parts.items():
            zout.writestr(name, data)
    print(f"{TEMPLATE}: {os.path.getsize(TEMPLATE)} bytes")


if __name__ == "__main__":
    main()
