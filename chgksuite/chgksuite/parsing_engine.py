import os
import re
import urllib.parse

import docx
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from chgksuite.typotools import (
    escape_underscores_except_urls,
)
from chgksuite.typotools import (
    remove_excessive_whitespace as rew,
)

_A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_R_LINK = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}link"
_IMAGE_EXTENSIONS = {
    "image/bmp": "bmp",
    "image/emf": "emf",
    "image/gif": "gif",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/tiff": "tiff",
    "image/webp": "webp",
    "image/wmf": "wmf",
}


def _generate_imgname(target_dir, ext, prefix=""):
    imgcounter = 1
    while os.path.isfile(
        os.path.join(target_dir, f"{prefix}{imgcounter:03}.{ext}")
    ):
        imgcounter += 1
    return f"{prefix}{imgcounter:03}.{ext}"


def _attr(element, name, default=None):
    return element.get(qn(name), default)


def _bool(element):
    if element is None:
        return False
    val = _attr(element, "w:val")
    return val not in ("0", "false", "False", "off")


def _iter_blocks(parent):
    if hasattr(parent, "element") and hasattr(parent.element, "body"):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._tc
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _style_name(paragraph):
    try:
        return paragraph.style.name or ""
    except (AttributeError, KeyError):
        return ""


def _style_id(paragraph):
    try:
        return paragraph.style.style_id or ""
    except (AttributeError, KeyError):
        return ""


def _heading_level(paragraph):
    style_name = _style_name(paragraph).lower()
    style_id = _style_id(paragraph).lower()
    for candidate in (style_name, style_id):
        m = re.search(r"heading\s*([1-6])", candidate)
        if m:
            return int(m.group(1))
        m = re.search(r"заголовок\s*([1-6])", candidate)
        if m:
            return int(m.group(1))
    return None


def _format_marker(bold, italic, underline):
    if italic and bold and underline:
        return "_" * 6
    if bold and underline:
        return "_" * 5
    if bold and italic:
        return "_" * 4
    if underline:
        return "_" * 3
    if bold:
        return "__"
    if italic:
        return "_"
    return ""


def _render_text(text, bold=False, italic=False, underline=False, preserve=False):
    if not text:
        return ""
    text = _escape_underscores(text)
    if not preserve:
        return text
    marker = _format_marker(bold, italic, underline)
    if not marker or not text.strip():
        return text
    match = re.match(r"^(\s*)(.*?)(\s*)$", text, re.DOTALL)
    leading, body, trailing = match.groups()
    return f"{leading}{marker}{body}{marker}{trailing}"


def _escape_underscores(text):
    return escape_underscores_except_urls(text)


def _run_formatting(run_element, paragraph):
    run = Run(run_element, paragraph)
    bold = run.bold
    italic = run.italic
    underline = run.underline
    if bold is None:
        bold = _bool(run_element.find(f"{qn('w:rPr')}/{qn('w:b')}"))
    if italic is None:
        italic = _bool(run_element.find(f"{qn('w:rPr')}/{qn('w:i')}"))
    if underline is None:
        underline = _bool(run_element.find(f"{qn('w:rPr')}/{qn('w:u')}"))
    return bool(bold), bool(italic), bool(underline)


def _image_extension(image_part):
    content_type = getattr(image_part, "content_type", "")
    if content_type in _IMAGE_EXTENSIONS:
        return _IMAGE_EXTENSIONS[content_type]
    partname = str(getattr(image_part, "partname", ""))
    _, ext = os.path.splitext(partname)
    return ext[1:] or "bin"


class _Numbering:
    def __init__(self, document):
        self.num_to_abstract = {}
        self.levels = {}
        self.overrides = {}
        try:
            root = document.part.numbering_part.element
        except (AttributeError, KeyError, NotImplementedError):
            return
        for abstract in root.findall(qn("w:abstractNum")):
            abstract_id = _attr(abstract, "w:abstractNumId")
            if abstract_id is None:
                continue
            for level in abstract.findall(qn("w:lvl")):
                ilvl = _attr(level, "w:ilvl", "0")
                fmt = level.find(qn("w:numFmt"))
                text = level.find(qn("w:lvlText"))
                start = level.find(qn("w:start"))
                self.levels[(abstract_id, ilvl)] = {
                    "fmt": _attr(fmt, "w:val", "decimal")
                    if fmt is not None
                    else "decimal",
                    "text": _attr(text, "w:val", "%1.")
                    if text is not None
                    else "%1.",
                    "start": int(_attr(start, "w:val", "1"))
                    if start is not None
                    else 1,
                }
        for num in root.findall(qn("w:num")):
            num_id = _attr(num, "w:numId")
            abstract = num.find(qn("w:abstractNumId"))
            abstract_id = _attr(abstract, "w:val") if abstract is not None else None
            if num_id is not None and abstract_id is not None:
                self.num_to_abstract[num_id] = abstract_id
            for override in num.findall(qn("w:lvlOverride")):
                ilvl = _attr(override, "w:ilvl", "0")
                start = override.find(qn("w:startOverride"))
                if start is not None:
                    self.overrides[(num_id, ilvl)] = int(_attr(start, "w:val", "1"))

    def level(self, num_id, ilvl):
        abstract_id = self.num_to_abstract.get(num_id)
        if abstract_id is None:
            return None
        return self.levels.get((abstract_id, ilvl)) or self.levels.get(
            (abstract_id, "0")
        )

    def is_ordered(self, num_id, ilvl):
        level = self.level(num_id, ilvl)
        if not level:
            return True
        return level["fmt"] != "bullet"

    def start(self, num_id, ilvl, preserve_start):
        if not preserve_start:
            return 1
        return self.overrides.get((num_id, ilvl)) or (
            self.level(num_id, ilvl) or {}
        ).get("start", 1)

    def prefix(self, num_id, ilvl, value):
        level = self.level(num_id, ilvl) or {}
        fmt = level.get("fmt", "decimal")
        template = level.get("text", "%1.")
        formatted = _format_list_number(value, fmt)
        if "%1" in template:
            prefix = template.replace("%1", formatted)
        else:
            prefix = f"{formatted}."
        return prefix.rstrip() + " "


def _format_list_number(value, fmt):
    if fmt == "lowerLetter":
        return _alpha_number(value).lower()
    if fmt == "upperLetter":
        return _alpha_number(value).upper()
    if fmt == "lowerRoman":
        return _roman_number(value).lower()
    if fmt == "upperRoman":
        return _roman_number(value).upper()
    return str(value)


def _alpha_number(value):
    result = ""
    while value > 0:
        value -= 1
        result = chr(ord("A") + value % 26) + result
        value //= 26
    return result or "A"


def _roman_number(value):
    numerals = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    result = ""
    for number, numeral in numerals:
        while value >= number:
            result += numeral
            value -= number
    return result or "I"


class _DocxTextConverter:
    def __init__(
        self,
        docxfile,
        args,
        target_dir,
        image_prefix,
        inject_heading_markers,
        preserve_ol_start,
        logger,
    ):
        self.document = docx.Document(docxfile)
        self.args = args
        self.target_dir = target_dir
        self.image_prefix = image_prefix
        self.inject_heading_markers = inject_heading_markers
        self.preserve_ol_start = preserve_ol_start
        self.logger = logger
        self.preserve_formatting = getattr(args, "preserve_formatting", False)
        self.links = getattr(args, "links", "unwrap") or "unwrap"
        self.numbering = _Numbering(self.document)
        self.list_counters = {}

    def convert(self):
        blocks = []
        for block in _iter_blocks(self.document):
            if isinstance(block, Paragraph):
                text = self.paragraph_text(block)
            else:
                text = self.table_text(block)
            blocks.append(text)
        return "\n\n".join(blocks)

    def paragraph_text(self, paragraph):
        text = self._paragraph_inline_text(paragraph)
        if not text.strip(" \t\r\n"):
            self._break_list_if_needed()
            return ""
        heading_level = _heading_level(paragraph)
        if self.inject_heading_markers and heading_level in (1, 2, 3):
            text = f"$$H{heading_level}$$ {text}"
        if self.inject_heading_markers and heading_level in (1, 2, 3):
            self._break_list_if_needed()
            list_prefix = ""
        else:
            list_prefix = self._list_prefix(paragraph)
        if list_prefix:
            text = list_prefix + text
        return text

    def table_text(self, table):
        rows = []
        for row in table.rows:
            row_data = []
            for cell in row.cells:
                cell_text = " ".join(self._cell_text(cell).split())
                row_data.append(cell_text)
            if row_data:
                rows.append(row_data)
        return _markdown_table(rows)

    def _cell_text(self, cell):
        chunks = []
        for block in _iter_blocks(cell):
            if isinstance(block, Paragraph):
                chunks.append(self.paragraph_text(block))
            else:
                chunks.append(self.table_text(block))
        return "\n".join(chunks)

    def _paragraph_inline_text(self, paragraph):
        chunks = []
        for child in paragraph._p.iterchildren():
            if child.tag == qn("w:r"):
                chunks.append(self._run_text(child, paragraph))
            elif child.tag == qn("w:hyperlink"):
                chunks.append(self._hyperlink_text(child, paragraph))
            elif child.tag != qn("w:del"):
                chunks.append(self._container_text(child, paragraph))
        return "".join(chunks)

    def _container_text(self, container, paragraph):
        chunks = []
        for child in container.iterchildren():
            if child.tag == qn("w:r"):
                chunks.append(self._run_text(child, paragraph))
            elif child.tag == qn("w:hyperlink"):
                chunks.append(self._hyperlink_text(child, paragraph))
            elif child.tag == qn("w:del"):
                continue
            else:
                chunks.append(self._container_text(child, paragraph))
        return "".join(chunks)

    def _hyperlink_text(self, hyperlink, paragraph):
        rendered_chunks = []
        plain_chunks = []
        for child in hyperlink.iterchildren():
            if child.tag != qn("w:r"):
                continue
            rendered_chunks.append(
                self._run_text(child, paragraph, suppress_underline=True)
            )
            plain_chunks.append(self._run_text(child, paragraph, plain=True))
        rendered = "".join(rendered_chunks)
        plain = rew("".join(plain_chunks))
        href = self._hyperlink_href(hyperlink, paragraph)
        if not href:
            return rendered
        if self.links == "old":
            return href if plain else ""
        if plain.startswith("http"):
            return rendered
        if (
            href.startswith("http")
            and plain.strip() not in href
            and urllib.parse.unquote(plain.strip())
            not in urllib.parse.unquote(href)
        ):
            return f"{rendered} ({href})"
        return rendered

    def _hyperlink_href(self, hyperlink, paragraph):
        r_id = hyperlink.get(_R_ID)
        if not r_id:
            return ""
        try:
            return paragraph.part.rels[r_id].target_ref
        except KeyError:
            return ""

    def _run_text(self, run_element, paragraph, plain=False, suppress_underline=False):
        if plain:
            preserve = False
            bold = italic = underline = False
        else:
            preserve = self.preserve_formatting
            bold, italic, underline = _run_formatting(run_element, paragraph)
            if suppress_underline:
                underline = False
        chunks = []
        buffer = []

        def flush_buffer():
            if not buffer:
                return
            text = "".join(buffer)
            buffer.clear()
            if plain:
                chunks.append(text)
            else:
                chunks.append(
                    _render_text(
                        text,
                        bold=bold,
                        italic=italic,
                        underline=underline,
                        preserve=preserve,
                    )
                )

        for child in run_element.iterchildren():
            if child.tag == qn("w:t"):
                buffer.append(child.text or "")
            elif child.tag == qn("w:tab"):
                buffer.append("\t")
            elif child.tag in (qn("w:br"), qn("w:cr")):
                buffer.append("\n")
            elif child.tag == qn("w:noBreakHyphen"):
                buffer.append("-")
            elif child.tag == qn("w:softHyphen"):
                continue
            elif child.tag in (qn("w:drawing"), qn("w:pict")):
                flush_buffer()
                if not plain:
                    chunks.extend(self._image_markers(child, paragraph))
        flush_buffer()
        return "".join(chunks)

    def _image_markers(self, element, paragraph):
        markers = []
        r_ids = []
        for blip in element.findall(f".//{_A_BLIP}"):
            r_id = blip.get(_R_EMBED) or blip.get(_R_LINK)
            if r_id:
                r_ids.append(r_id)
        for image_data in element.findall(f".//{_V_IMAGEDATA}"):
            r_id = image_data.get(_R_ID)
            if r_id:
                r_ids.append(r_id)
        for r_id in r_ids:
            markers.append(self._extract_image(r_id, paragraph))
        return markers

    def _extract_image(self, r_id, paragraph):
        try:
            image_part = paragraph.part.related_parts[r_id]
        except KeyError:
            return "(img BROKEN_IMAGE)"
        ext = _image_extension(image_part)
        imgname = _generate_imgname(self.target_dir, ext, prefix=self.image_prefix)
        with open(os.path.join(self.target_dir, imgname), "wb") as f:
            f.write(image_part.blob)
        return f"(img {os.path.basename(imgname)})"

    def _list_prefix(self, paragraph):
        num_id, ilvl = self._paragraph_numbering(paragraph)
        if num_id is None:
            self._break_list_if_needed()
            return ""
        key = (num_id, ilvl)
        if key not in self.list_counters:
            self.list_counters[key] = self.numbering.start(
                num_id, ilvl, self.preserve_ol_start
            )
        else:
            self.list_counters[key] += 1
        return self.numbering.prefix(num_id, ilvl, self.list_counters[key])

    def _break_list_if_needed(self):
        if not self.preserve_ol_start:
            self.list_counters.clear()

    def _paragraph_numbering(self, paragraph):
        direct = self._num_pr_values(paragraph._p)
        style = self._style_num_pr_values(paragraph)
        num_id = direct[0] or style[0]
        ilvl = direct[1] or style[1] or "0"
        if num_id and self.numbering.is_ordered(num_id, ilvl):
            return num_id, ilvl
        if num_id:
            return None, None
        style_name = _style_name(paragraph).lower()
        style_id = _style_id(paragraph).lower()
        if (
            ("number" in style_name or "number" in style_id or "номер" in style_name)
            and "bullet" not in style_name
            and "bullet" not in style_id
        ):
            return f"style:{style_id or style_name}", "0"
        return None, None

    def _num_pr_values(self, element):
        p_pr = element.find(qn("w:pPr"))
        if p_pr is None:
            return None, None
        num_pr = p_pr.find(qn("w:numPr"))
        return self._num_pr_ids(num_pr)

    def _style_num_pr_values(self, paragraph):
        try:
            style_element = paragraph.style.element
        except (AttributeError, KeyError):
            return None, None
        p_pr = style_element.find(qn("w:pPr"))
        if p_pr is None:
            return None, None
        num_pr = p_pr.find(qn("w:numPr"))
        return self._num_pr_ids(num_pr)

    @staticmethod
    def _num_pr_ids(num_pr):
        if num_pr is None:
            return None, None
        num_id = num_pr.find(qn("w:numId"))
        ilvl = num_pr.find(qn("w:ilvl"))
        return (
            _attr(num_id, "w:val") if num_id is not None else None,
            _attr(ilvl, "w:val") if ilvl is not None else None,
        )


def _markdown_table(rows):
    if not rows:
        return ""
    max_cols = max(len(row) for row in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")
    widths = [
        max(max(len(row[col]) for row in rows) + 2, 3) for col in range(max_cols)
    ]
    lines = [
        "|"
        + "|".join(_center_cell(cell, widths[i]) for i, cell in enumerate(rows[0]))
        + "|",
        "|" + "|".join("-" * width for width in widths) + "|",
    ]
    for row in rows[1:]:
        lines.append(
            "|"
            + "|".join(_center_cell(cell, widths[i]) for i, cell in enumerate(row))
            + "|"
        )
    return "\n".join(lines)


def _center_cell(text, width):
    text = text.strip()
    padding = width - len(text)
    left = padding // 2
    right = padding - left
    return " " * left + text + " " * right


def python_docx_to_text(
    docxfile,
    args,
    target_dir,
    image_prefix,
    inject_heading_markers,
    preserve_ol_start,
    logger,
):
    converter = _DocxTextConverter(
        docxfile,
        args,
        target_dir,
        image_prefix,
        inject_heading_markers,
        preserve_ol_start,
        logger,
    )
    return converter.convert()
