import argparse
import csv
import json
import logging
import os
import posixpath
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import openpyxl
import toml


class ChgksuiteError(Exception):
    """Base class for errors chgksuite raises on its own."""


HYPERLINK_SAFE_CHARS = "%/:?#[]@!$&'()*+,;="
NO_BREAK_HYPHEN_REPLACEMENT = "\u2060-\u2060"
URL_BREAK_AFTER_CHARS = "/.-_\u2011?&=%#:"

QUESTION_LABELS = [
    "handout",
    "question",
    "answer",
    "zachet",
    "nezachet",
    "comment",
    "source",
    "author",
    "number",
    "setcounter",
]
SEP = "\n"
try:
    ENC = sys.stdout.encoding or "utf8"
except AttributeError:
    ENC = "utf8"

lastdir = os.path.join(os.path.dirname(os.path.abspath("__file__")), "lastdir")


def get_chgksuite_dir():
    chgksuite_dir = os.path.join(os.path.expanduser("~"), ".chgksuite")
    if not os.path.isdir(chgksuite_dir):
        os.mkdir(chgksuite_dir)
    return chgksuite_dir


def init_logger(logger_name, debug=False):
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        log_dir = get_chgksuite_dir()
        log_path = os.path.join(log_dir, f"{logger_name}.log")
        fh = logging.FileHandler(log_path, encoding="utf8")
        fh.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        if debug:
            ch.setLevel(logging.DEBUG)
        else:
            ch.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s | %(message)s")
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


def load_settings():
    chgksuite_dir = get_chgksuite_dir()
    settings_file = os.path.join(chgksuite_dir, "settings.toml")
    if not os.path.isfile(settings_file):
        return {}
    return toml.loads(Path(settings_file).read_text("utf8"))


def get_source_dirs():
    if getattr(sys, "frozen", False):
        sourcedir = os.path.dirname(sys.executable)
        resourcedir = os.path.join(sourcedir, "resources")
    else:
        sourcedir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
        resourcedir = os.path.join(sourcedir, "resources")
    return sourcedir, resourcedir


class DefaultArgs:
    console_mode = True
    debug = False
    fix_spans = False
    labels_file = os.path.join(get_source_dirs()[1], "labels_ru.toml")
    language = "ru"
    links = "unwrap"
    numbers_handling = "default"
    parsing_engine = "python_docx"
    regexes = os.path.join(get_source_dirs()[1], "regexes_ru.json")
    single_number_line_handling = "smart"
    typography_accents = "on"
    typography_dashes = "on"
    typography_percent = "on"
    typography_quotes = "on"
    typography_whitespace = "on"

    def __getattr__(self, attribute):
        try:
            return object.__getattr__(self, attribute)
        except AttributeError:
            return None

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def set_lastdir(path):
    chgksuite_dir = get_chgksuite_dir()
    lastdir = os.path.join(chgksuite_dir, "lastdir")
    with open(lastdir, "w", encoding="utf-8") as f:
        f.write(path)


def get_lastdir():
    chgksuite_dir = get_chgksuite_dir()
    lastdir = os.path.join(chgksuite_dir, "lastdir")
    if os.path.isfile(lastdir):
        with open(lastdir, "r", encoding="utf-8") as f:
            return f.read().rstrip()
    return "."


def retry_wrapper_factory(logger):
    def retry_wrapper(func, args=None, kwargs=None, retries=3):
        cntr = 0
        ret = None
        if not args:
            args = []
        if not kwargs:
            kwargs = {}
        while not ret and cntr < retries:
            try:
                ret = func(*args, **kwargs)
            except Exception:
                logger.exception("exception in retried call")
                time.sleep(5)
                cntr += 1
        return ret

    return retry_wrapper


def ensure_utf8(s):
    if isinstance(s, bytes):
        return s.decode("utf8", errors="replace")
    return s


def read_text_file(filepath, encoding="utf-8"):
    """Read a text file, fixing corrupted line endings (\r\r\n -> \n) if present."""
    with open(filepath, "rb") as f:
        raw = f.read()
    # Fix corrupted line endings at byte level before decoding
    if b"\r\r\n" in raw:
        raw = raw.replace(b"\r\r\n", b"\n")
    text = raw.decode(encoding)
    # Normalize any remaining line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def pil_image_to_jpeg_bytes(image, quality=80, exif_transpose=False):
    from PIL import Image, ImageOps

    if exif_transpose:
        image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        background.alpha_composite(image)
        image = background.convert("RGB")
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    output = BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


def pil_image_has_transparency(image):
    if image.mode in ("RGBA", "LA"):
        return image.getchannel("A").getextrema()[0] < 255
    if image.mode == "P" and "transparency" in image.info:
        transparency = image.info["transparency"]
        if isinstance(transparency, int):
            return any(pixel == transparency for pixel in image.getdata())
        return any(alpha < 255 for alpha in transparency)
    return False


def pil_image_to_png_bytes(image, exif_transpose=False, compress_level=9):
    from PIL import ImageOps

    if exif_transpose:
        image = ImageOps.exif_transpose(image)

    output = BytesIO()
    save_kwargs = {"format": "PNG", "optimize": True, "compress_level": compress_level}
    if image.mode == "P" and "transparency" in image.info:
        save_kwargs["transparency"] = image.info["transparency"]
    image.save(output, **save_kwargs)
    return output.getvalue()


def image_data_to_jpeg_bytes(image_data, quality=80, exif_transpose=False):
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(image_data)) as image:
            return pil_image_to_jpeg_bytes(
                image, quality=quality, exif_transpose=exif_transpose
            )
    except (OSError, UnidentifiedImageError):
        return None


def optimize_raster_image_data(
    image_data, original_extension="", quality=80, exif_transpose=False
):
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(BytesIO(image_data)) as image:
            if exif_transpose:
                image = ImageOps.exif_transpose(image)
            has_transparency = pil_image_has_transparency(image)
            candidates = []
            if has_transparency:
                candidates.append(
                    (
                        "png",
                        "image/png",
                        pil_image_to_png_bytes(image),
                    )
                )
            else:
                candidates.append(
                    (
                        "jpg",
                        "image/jpeg",
                        pil_image_to_jpeg_bytes(image, quality=quality),
                    )
                )
                if original_extension.lower().lstrip(".") == "png":
                    candidates.append(
                        (
                            "png",
                            "image/png",
                            pil_image_to_png_bytes(image),
                        )
                    )
    except (OSError, UnidentifiedImageError):
        return None

    candidates = [
        candidate for candidate in candidates if len(candidate[2]) < len(image_data)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: len(candidate[2]))


def image_file_to_jpeg_bytes(path, quality=80, exif_transpose=True):
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            return pil_image_to_jpeg_bytes(
                image, quality=quality, exif_transpose=exif_transpose
            )
    except (OSError, UnidentifiedImageError):
        return None


def save_pil_image_as_jpeg(image, path, quality=80, exif_transpose=False):
    jpeg_data = pil_image_to_jpeg_bytes(
        image, quality=quality, exif_transpose=exif_transpose
    )
    with open(path, "wb") as output:
        output.write(jpeg_data)


_OOXML_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_OOXML_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OOXML_IMAGE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)


def _ooxml_xml_bytes(root, default_namespace=None):
    if default_namespace:
        ET.register_namespace("", default_namespace)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _load_ooxml_xml_part(package_zip, name, default_root):
    try:
        return ET.fromstring(package_zip.read(name))
    except KeyError:
        return default_root


def _ensure_ooxml_content_type_default(content_types_root, extension, content_type):
    for default in content_types_root.findall(f"{{{_OOXML_CONTENT_TYPES_NS}}}Default"):
        if default.get("Extension") == extension:
            default.set("ContentType", content_type)
            return
    default = ET.Element(
        f"{{{_OOXML_CONTENT_TYPES_NS}}}Default",
        {"Extension": extension, "ContentType": content_type},
    )
    insert_at = 0
    for index, child in enumerate(list(content_types_root)):
        if child.tag == f"{{{_OOXML_CONTENT_TYPES_NS}}}Override":
            insert_at = index
            break
        insert_at = index + 1
    content_types_root.insert(insert_at, default)


def _remove_ooxml_content_type_override(content_types_root, part_name):
    for override in list(
        content_types_root.findall(f"{{{_OOXML_CONTENT_TYPES_NS}}}Override")
    ):
        if override.get("PartName") == part_name:
            content_types_root.remove(override)


def _ooxml_rels_source_part(rels_part_name):
    rels_dir = posixpath.dirname(rels_part_name)
    if posixpath.basename(rels_dir) != "_rels":
        return None
    source_dir = posixpath.dirname(rels_dir)
    source_name = posixpath.basename(rels_part_name)[: -len(".rels")]
    if not source_dir:
        return source_name
    return posixpath.join(source_dir, source_name)


def _ooxml_relationship_target_part(rels_part_name, target):
    if not target:
        return None
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    source_part = _ooxml_rels_source_part(rels_part_name)
    if source_part is None:
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def _ooxml_relationship_target_for_part(rels_part_name, part_name):
    source_part = _ooxml_rels_source_part(rels_part_name)
    if source_part is None:
        return part_name
    return posixpath.relpath(part_name, posixpath.dirname(source_part))


def _next_ooxml_media_part_name(existing_names, original_part_name, extension="jpg"):
    dirname = posixpath.dirname(original_part_name)
    stem = posixpath.splitext(posixpath.basename(original_part_name))[0]
    candidate = posixpath.join(dirname, f"{stem}.{extension}")
    if candidate not in existing_names:
        return candidate

    index = 1
    while True:
        candidate = posixpath.join(dirname, f"{stem}_{index}.{extension}")
        if candidate not in existing_names:
            return candidate
        index += 1


def _rewrite_zip_package(package_path, replacements, removals=()):
    output_dir = os.path.dirname(os.path.abspath(package_path)) or "."
    suffix = os.path.splitext(package_path)[1]
    fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=output_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(package_path, "r") as source_zip, zipfile.ZipFile(
            temp_path, "w", zipfile.ZIP_DEFLATED
        ) as target_zip:
            replaced_names = set(replacements)
            removed_names = set(removals)
            for item in source_zip.infolist():
                if item.filename in replaced_names or item.filename in removed_names:
                    continue
                target_zip.writestr(item, source_zip.read(item.filename))
            for name, data in replacements.items():
                target_zip.writestr(name, data)
        os.replace(temp_path, package_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def optimize_ooxml_images(package_path, media_prefix, rels_prefix, quality=80):
    with zipfile.ZipFile(package_path, "r") as package_zip:
        existing_names = set(package_zip.namelist())
        media_names = [
            name
            for name in existing_names
            if name.startswith(media_prefix) and not name.endswith("/")
        ]
        content_types_root = _load_ooxml_xml_part(
            package_zip,
            "[Content_Types].xml",
            ET.Element(f"{{{_OOXML_CONTENT_TYPES_NS}}}Types"),
        )
        rels_parts = {}
        for name in existing_names:
            if not name.endswith(".rels"):
                continue
            if rels_prefix and not name.startswith(rels_prefix):
                continue
            try:
                rels_parts[name] = ET.fromstring(package_zip.read(name))
            except ET.ParseError:
                continue
        media_data = {name: package_zip.read(name) for name in media_names}

    replacements = {}
    removals = set()
    optimized_parts = {}
    renamed_parts = {}
    optimized_content_types = {}
    reserved_names = set(existing_names)

    for media_name, image_data in media_data.items():
        original_extension = posixpath.splitext(media_name)[1].lower().lstrip(".")
        optimized = optimize_raster_image_data(
            image_data, original_extension=original_extension, quality=quality
        )
        if not optimized:
            continue

        optimized_extension, content_type, optimized_data = optimized
        same_extension = optimized_extension == original_extension or (
            optimized_extension == "jpg" and original_extension == "jpeg"
        )
        if same_extension:
            new_name = media_name
            content_extension = original_extension
        else:
            new_name = _next_ooxml_media_part_name(
                reserved_names, media_name, extension=optimized_extension
            )
            reserved_names.add(new_name)
            removals.add(media_name)
            renamed_parts[media_name] = new_name
            content_extension = optimized_extension

        replacements[new_name] = optimized_data
        optimized_parts[media_name] = new_name
        optimized_content_types[content_extension] = content_type

    if not optimized_parts:
        return {}

    for rels_name, rels_root in rels_parts.items():
        changed = False
        for rel in rels_root.findall(f"{{{_OOXML_PACKAGE_REL_NS}}}Relationship"):
            if (
                rel.get("Type") != _OOXML_IMAGE_REL_TYPE
                or rel.get("TargetMode") == "External"
            ):
                continue
            old_part_name = _ooxml_relationship_target_part(
                rels_name, rel.get("Target", "")
            )
            if old_part_name not in renamed_parts:
                continue
            rel.set(
                "Target",
                _ooxml_relationship_target_for_part(
                    rels_name, renamed_parts[old_part_name]
                ),
            )
            changed = True
        if changed:
            replacements[rels_name] = _ooxml_xml_bytes(
                rels_root, default_namespace=_OOXML_PACKAGE_REL_NS
            )

    for extension, content_type in sorted(optimized_content_types.items()):
        _ensure_ooxml_content_type_default(content_types_root, extension, content_type)
    if optimized_content_types.get("jpg") == "image/jpeg":
        _ensure_ooxml_content_type_default(content_types_root, "jpeg", "image/jpeg")
    for old_part_name in renamed_parts:
        _remove_ooxml_content_type_override(content_types_root, f"/{old_part_name}")
    replacements["[Content_Types].xml"] = _ooxml_xml_bytes(
        content_types_root, default_namespace=_OOXML_CONTENT_TYPES_NS
    )

    _rewrite_zip_package(package_path, replacements, removals=removals)
    return optimized_parts


class DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class DefaultNamespace(argparse.Namespace):
    def __init__(self, *args, **kwargs):
        for ns in args:
            if isinstance(ns, argparse.Namespace):
                for name in vars(ns):
                    setattr(self, name, vars(ns)[name])
        for name, value in kwargs.items():
            setattr(self, name, value)

    def __getattribute__(self, name):
        try:
            return argparse.Namespace.__getattribute__(self, name)
        except AttributeError:
            return


def log_wrap(s, pretty_print=True):
    try_to_unescape = True
    if pretty_print and isinstance(s, (dict, list)):
        s = json.dumps(s, indent=2, ensure_ascii=False, sort_keys=True)
        try_to_unescape = False
    s = format(s)
    if sys.version_info.major == 2 and try_to_unescape:
        try:
            s = s.decode("unicode_escape")
        except UnicodeEncodeError:
            pass
    return s.encode(ENC, errors="replace").decode(ENC)


def check_question(question, logger=None, required_fields=None):
    if required_fields is None:
        required_fields = {"question", "answer", "source", "author"}
    warnings = []
    for el in required_fields:
        if el not in question:
            warnings.append(el)
    if len(warnings) > 0:
        logger.warning(
            "WARNING: question {} lacks the following fields: {}{}".format(
                log_wrap(question), ", ".join(warnings), SEP
            )
        )


def remove_double_separators(s):
    return re.sub(rf"({SEP})+", SEP, s)


def tryint(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return


def _results_table_to_masks(rows, logger=None, source=""):
    """Convert a rating.chgk.info "вопросная таблица" into per-team results.

    ``rows`` is any iterable of rows, where each row is a sequence of cell
    values (as produced by ``csv.reader`` or ``openpyxl``'s ``iter_rows``). Both
    layouts the rating site exports are supported:

    * "full" -- one row per team: ``id, name, city, q1, q2, ...``
    * "tour" -- one row per team per tour, with a "Тур" column:
      ``id, name, city, tour, q1, q2, ...``

    Leading blank rows (and a UTF-8 BOM, for CSV) are skipped. Unexpected or
    disputed cell values (anything that is not 0/1, e.g. unresolved
    controversials) are counted as not taken and reported via ``logger`` instead
    of aborting.

    Returns a list of ``{"team": {"id": ...}, "current": {"name": ...},
    "mask": "0101..."}`` dicts.
    """
    logger = logger or DummyLogger()
    res_by_tour = defaultdict(lambda: defaultdict(list))
    tour_len = defaultdict(lambda: 0)
    table_type = None
    disputed = []
    for row in rows:
        if not any(cell not in (None, "") for cell in row):
            continue
        if table_type is None:
            # Locate the header row (the one labelling the "Название" column),
            # skipping any leading blank/garbage rows.
            if len(row) > 1 and str(row[1]).strip() == "Название":
                table_type = "tour" if (len(row) > 3 and row[3] == "Тур") else "full"
            continue
        team_id = tryint(row[0])
        if team_id is None:
            continue
        team_name = row[1]
        if table_type == "tour":
            tour = tryint(row[3]) or 0
            raw = row[4:]
        else:
            tour = 1
            raw = row[3:]
        mask_row = []
        for element in raw:
            value = tryint(element)
            if value == 1:
                mask_row.append("1")
            elif value == 0 or element in (None, ""):
                mask_row.append("0")
            else:
                mask_row.append("0")
                disputed.append((team_name, element))
        tour_len[tour] = max(tour_len[tour], len(mask_row))
        res_by_tour[(team_id, team_name)][tour] = mask_row

    if table_type is None:
        logger.warning(
            f"Не удалось найти заголовок вопросной таблицы (строку со столбцом "
            f"«Название»): путь={source}."
        )
        return []
    if disputed:
        team, value = disputed[0]
        logger.warning(
            f"В расплюсовке найдены нерассмотренные спорные или неожиданные "
            f"значения ({len(disputed)} шт.), они засчитаны как неверные. "
            f"Например: значение={value!r}, команда={team!r}, путь={source}."
        )

    results = []
    tours = sorted(tour_len)
    for (team_id, team_name), by_tour in res_by_tour.items():
        mask = []
        for tour in tours:
            team_res = list(by_tour.get(tour) or [])
            if len(team_res) < tour_len[tour]:
                team_res += ["0"] * (tour_len[tour] - len(team_res))
            mask.extend(team_res)
        results.append(
            {
                "team": {"id": team_id},
                "current": {"name": team_name},
                "mask": "".join(mask),
            }
        )
    return results


def xlsx_to_results(xlsx_file_path, logger=None):
    wb = openpyxl.load_workbook(xlsx_file_path, data_only=True)
    sheet = wb.active
    return _results_table_to_masks(
        sheet.iter_rows(values_only=True), logger=logger, source=xlsx_file_path
    )


def custom_csv_to_results(csv_file_path, logger=None, **kwargs):
    # encoding="utf-8-sig" transparently strips a leading BOM if present.
    with open(csv_file_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, **kwargs))
    return _results_table_to_masks(rows, logger=logger, source=csv_file_path)


def replace_escaped(s):
    return s.replace("\\[", "[").replace("\\]", "]")


def compose_4s(structure, args=None):
    types_mapping = {
        "meta": "# ",
        "section": "## ",
        "tour": "## ",
        "tourrev": "## ",
        "battle": "#B ",
        "round": "#R ",
        "theme": "#T ",
        "editor": "#EDITOR ",
        "heading": "### ",
        "ljheading": "###LJ ",
        "date": "#DATE ",
        "question": "? ",
        "answer": "! ",
        "zachet": "= ",
        "nezachet": "!= ",
        "source": "^ ",
        "comment": "/ ",
        "author": "@ ",
        "handout": "> ",
        "Question": None,
    }

    def format_element(z):
        if isinstance(z, str):
            return remove_double_separators(z)
        elif isinstance(z, list):
            if isinstance(z[1], list):
                return (
                    remove_double_separators(z[0])
                    + SEP
                    + "- "
                    + (f"{SEP}- ").join(
                        [remove_double_separators(x) for x in z[1]]
                    )
                )
            else:
                return (
                    SEP
                    + "- "
                    + (f"{SEP}- ").join(
                        [remove_double_separators(x) for x in z]
                    )
                )

    def is_zero(s):
        return str(s).startswith("0") or not tryint(s)

    result = ""
    first_number = True
    for element in structure:
        if element[0] in types_mapping and types_mapping[element[0]]:
            value = element[1]
            if element[0] == "theme" and isinstance(value, dict):
                value = value["label"]
            result += types_mapping[element[0]] + format_element(value) + SEP + SEP
        elif element[0] == "Question":
            tmp = ""
            overrides = element[1].get("overrides") or {}
            if "number" in element[1]:
                if not args.numbers_handling or args.numbers_handling == "default":
                    if is_zero(element[1]["number"]):
                        tmp += "№ " + str(element[1]["number"]) + SEP
                    elif first_number and tryint(element[1]["number"]) > 1:
                        tmp += "№№ " + str(element[1]["number"]) + SEP
                elif args.numbers_handling == "all":
                    tmp += "№ " + str(element[1]["number"]) + SEP
                if not is_zero(element[1]["number"]):
                    first_number = False
            for label in QUESTION_LABELS:
                override_label = (
                    "" if label not in overrides else (f"!!{overrides[label]} ")
                )
                if label in element[1] and label in types_mapping:
                    tmp += (
                        types_mapping[label]
                        + override_label
                        + format_element(element[1][label])
                        + SEP
                    )
            tmp = re.sub(rf"{SEP}+", SEP, tmp)
            result += tmp + SEP
    return result
