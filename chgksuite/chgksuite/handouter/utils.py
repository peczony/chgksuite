import logging
import os
import tempfile
from io import BytesIO

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    StreamObject,
    TextStringObject,
)

from chgksuite.common import optimize_raster_image_data, pil_image_to_jpeg_bytes
from chgksuite.handouter.installer import escape_typst

logger = logging.getLogger(__name__)

RESERVED_WORDS = [
    "image",
    "for_question",
    "columns",
    "rows",
    "resize_image",
    "font_size",
    "font_family",
    "no_center",
    "raw_tex",
    "color",
    "handouts_per_team",
    "grouping",
    "rotate",
    "tikz_mm",
    "hspace",
    "vspace",
    "max_width",
]


VECTOR_IMAGE_EXTENSIONS = {".ai", ".eps", ".pdf", ".svg"}


def _pdf_deref(obj):
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def _pdf_raw_get(obj, key):
    if hasattr(obj, "raw_get"):
        return obj.raw_get(key)
    return obj.get(key)


def _pdf_stream_raw_size(obj):
    stream = _pdf_deref(obj)
    data = getattr(stream, "_data", None)
    if data is None:
        return 0
    return len(data)


def _pdf_lookup_bytes(lookup):
    lookup = _pdf_deref(lookup)
    if isinstance(lookup, (bytes, bytearray)):
        return bytes(lookup)
    if isinstance(lookup, ByteStringObject):
        return bytes(lookup)
    if isinstance(lookup, TextStringObject):
        original_bytes = getattr(lookup, "original_bytes", None)
        if original_bytes is not None:
            return original_bytes
        return lookup.encode("latin-1")
    if not hasattr(lookup, "get_data"):
        raise TypeError("unsupported PDF indexed color lookup")
    return lookup.get_data()


def _pdf_image_to_pillow(stream):
    width = int(stream.get("/Width") or 0)
    height = int(stream.get("/Height") or 0)
    bits_per_component = int(stream.get("/BitsPerComponent") or 0)
    if width <= 0 or height <= 0 or bits_per_component != 8:
        return None

    color_space = _pdf_deref(stream.get("/ColorSpace"))
    data = stream.get_data()
    mode = None
    expected_size = None

    if color_space == "/DeviceRGB":
        mode = "RGB"
        expected_size = width * height * 3
    elif color_space == "/DeviceGray":
        mode = "L"
        expected_size = width * height
    elif color_space == "/DeviceCMYK":
        mode = "CMYK"
        expected_size = width * height * 4
    elif isinstance(color_space, ArrayObject) and color_space:
        color_space_name = color_space[0]
        if color_space_name == "/CalRGB":
            mode = "RGB"
            expected_size = width * height * 3
        elif color_space_name == "/ICCBased":
            icc_profile = _pdf_deref(color_space[1])
            components = int(icc_profile.get("/N") or 3)
            mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(components)
            expected_size = width * height * components if mode else None
        elif color_space_name == "/Indexed":
            base_color_space = _pdf_deref(color_space[1])
            if base_color_space != "/DeviceRGB":
                return None
            max_index = int(color_space[2])
            try:
                lookup = _pdf_lookup_bytes(color_space[3])
            except (AttributeError, TypeError, UnicodeEncodeError):
                return None
            expected_size = width * height
            if len(data) < expected_size:
                return None
            image = Image.frombytes("P", (width, height), data[:expected_size])
            palette = lookup[: (max_index + 1) * 3]
            image.putpalette(palette + b"\x00" * max(0, 768 - len(palette)))
            return image.convert("RGB")

    if mode is None or expected_size is None or len(data) < expected_size:
        return None

    image = Image.frombytes(mode, (width, height), data[:expected_size])
    if mode == "CMYK":
        return image.convert("RGB")
    return image


def _flatten_pdf_image_alpha(image, stream):
    smask = stream.get("/SMask")
    if smask is None:
        return image, False

    smask = _pdf_deref(smask)
    width, height = image.size
    if int(smask.get("/Width") or 0) != width or int(smask.get("/Height") or 0) != height:
        return None, False
    if int(smask.get("/BitsPerComponent") or 0) != 8:
        return None, False

    alpha_data = smask.get_data()
    if len(alpha_data) < width * height:
        return None, False

    alpha = Image.frombytes("L", (width, height), alpha_data[: width * height])
    image = image.convert("RGBA")
    image.putalpha(alpha)
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    background.alpha_composite(image)
    return background.convert("RGB"), True


def _recompress_pdf_image(stream, quality=80):
    if stream.get("/Subtype") != "/Image":
        return False
    if stream.get("/Mask") is not None or stream.get("/Decode") is not None:
        return False

    try:
        image = _pdf_image_to_pillow(stream)
    except (OSError, ValueError, NotImplementedError):
        return False
    if image is None:
        return False

    image, flattened_alpha = _flatten_pdf_image_alpha(image, stream)
    if image is None:
        return False
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    jpeg_data = pil_image_to_jpeg_bytes(image, quality=quality)

    old_size = _pdf_stream_raw_size(stream)
    if flattened_alpha:
        old_size += _pdf_stream_raw_size(stream.get("/SMask"))
    if not old_size:
        old_size = len(stream.get_data())
    if len(jpeg_data) >= old_size:
        return False

    stream._data = jpeg_data
    stream[NameObject("/Filter")] = NameObject("/DCTDecode")
    stream[NameObject("/ColorSpace")] = NameObject(
        "/DeviceGray" if image.mode == "L" else "/DeviceRGB"
    )
    stream[NameObject("/BitsPerComponent")] = NumberObject(8)
    for key in ("/DecodeParms", "/DP", "/SMask", "/Length"):
        if key in stream:
            del stream[NameObject(key)]
    return True


def _optimize_pdf_resource_images(resources, seen, quality=80):
    resources = _pdf_deref(resources)
    if not resources:
        return 0

    xobjects = _pdf_deref(resources.get("/XObject"))
    if not xobjects:
        return 0

    optimized = 0
    for ref in xobjects.values():
        obj = _pdf_deref(ref)
        key = (
            (ref.idnum, ref.generation)
            if isinstance(ref, IndirectObject)
            else id(obj)
        )
        if key in seen:
            continue
        seen.add(key)

        subtype = obj.get("/Subtype")
        if subtype == "/Image":
            optimized += int(_recompress_pdf_image(obj, quality=quality))
        elif subtype == "/Form":
            optimized += _optimize_pdf_resource_images(
                obj.get("/Resources"), seen, quality=quality
            )
    return optimized


def _pdf_object_fingerprint(obj, cache=None, visiting=None):
    if cache is None:
        cache = {}
    if visiting is None:
        visiting = set()

    if isinstance(obj, IndirectObject):
        key = (id(obj.pdf), obj.idnum, obj.generation)
        if key in cache:
            return cache[key]
        if key in visiting:
            return ("cycle", obj.idnum, obj.generation)
        visiting.add(key)
        fingerprint = _pdf_object_fingerprint(obj.get_object(), cache, visiting)
        visiting.remove(key)
        cache[key] = fingerprint
        return fingerprint

    if isinstance(obj, StreamObject):
        try:
            data = obj.get_data()
        except Exception:
            logger.exception("could not read PDF stream object data")
            data = getattr(obj, "_data", b"") or b""
        return (
            "stream",
            data,
            _pdf_dictionary_fingerprint(obj, cache, visiting),
        )

    if isinstance(obj, DictionaryObject):
        return _pdf_dictionary_fingerprint(obj, cache, visiting)

    if isinstance(obj, ArrayObject):
        return (
            "array",
            tuple(_pdf_object_fingerprint(item, cache, visiting) for item in obj),
        )

    if isinstance(obj, (bytes, bytearray)):
        return ("bytes", bytes(obj))
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return ("value", type(obj).__name__, obj)
    return ("value", type(obj).__name__, repr(obj))


def _pdf_dictionary_fingerprint(obj, cache, visiting):
    items = []
    for key in sorted(obj.keys(), key=str):
        if key == "/Length":
            continue
        items.append(
            (
                str(key),
                _pdf_object_fingerprint(_pdf_raw_get(obj, key), cache, visiting),
            )
        )
    return ("dict", tuple(items))


def _deduplicate_pdf_form_xobjects(resources, canonical_forms, fingerprint_cache):
    resources = _pdf_deref(resources)
    if not resources:
        return 0

    xobjects = _pdf_deref(resources.get("/XObject"))
    if not xobjects:
        return 0

    deduplicated = 0
    for name in list(xobjects.keys()):
        ref = _pdf_raw_get(xobjects, name)
        obj = _pdf_deref(ref)
        subtype = obj.get("/Subtype")
        if subtype != "/Form":
            continue

        deduplicated += _deduplicate_pdf_form_xobjects(
            obj.get("/Resources"), canonical_forms, fingerprint_cache
        )
        fingerprint = _pdf_object_fingerprint(obj, fingerprint_cache)
        canonical_ref = canonical_forms.get(fingerprint)
        if canonical_ref is None:
            if isinstance(ref, IndirectObject):
                canonical_forms[fingerprint] = ref
            continue
        if isinstance(ref, IndirectObject) and ref == canonical_ref:
            continue
        xobjects[NameObject(str(name))] = canonical_ref
        deduplicated += 1

    return deduplicated


def _canonicalize_pdf_ref(ref, canonical_objects, visiting_refs):
    if not isinstance(ref, IndirectObject):
        return ref, 0

    key = (id(ref.pdf), ref.idnum, ref.generation)
    if key in visiting_refs:
        return ref, 0

    visiting_refs.add(key)
    obj = ref.get_object()
    changes = _canonicalize_pdf_object_refs(obj, canonical_objects, visiting_refs)
    visiting_refs.remove(key)

    fingerprint = _pdf_object_fingerprint(obj)
    canonical_ref = canonical_objects.get(fingerprint)
    if canonical_ref is None:
        canonical_objects[fingerprint] = ref
        return ref, changes
    if canonical_ref == ref:
        return ref, changes
    return canonical_ref, changes + 1


def _canonicalize_pdf_value(value, canonical_objects, visiting_refs):
    if isinstance(value, IndirectObject):
        return _canonicalize_pdf_ref(value, canonical_objects, visiting_refs)
    if isinstance(value, (DictionaryObject, StreamObject, ArrayObject)):
        return value, _canonicalize_pdf_object_refs(
            value, canonical_objects, visiting_refs
        )
    return value, 0


def _canonicalize_pdf_object_refs(obj, canonical_objects, visiting_refs):
    changes = 0
    if isinstance(obj, (DictionaryObject, StreamObject)):
        for key in list(obj.keys()):
            raw_value = _pdf_raw_get(obj, key)
            new_value, value_changes = _canonicalize_pdf_value(
                raw_value, canonical_objects, visiting_refs
            )
            changes += value_changes
            if new_value is not raw_value:
                obj[NameObject(str(key))] = new_value
    elif isinstance(obj, ArrayObject):
        for index, item in enumerate(list(obj)):
            new_value, value_changes = _canonicalize_pdf_value(
                item, canonical_objects, visiting_refs
            )
            changes += value_changes
            if new_value is not item:
                obj[index] = new_value
    return changes


def _deduplicate_pdf_page_refs(writer):
    canonical_objects = {}
    for page in writer.pages:
        for key in ("/Resources", "/Contents"):
            if key not in page:
                continue
            raw_value = _pdf_raw_get(page, key)
            new_value, _ = _canonicalize_pdf_value(raw_value, canonical_objects, set())
            if new_value is not raw_value:
                page[NameObject(key)] = new_value


def _write_pypdf_compressed(input_path, output_path, image_quality=80):
    reader = PdfReader(input_path)
    writer = PdfWriter()
    seen_images = set()

    for page in reader.pages:
        writer.add_page(page)
        writer_page = writer.pages[-1]
        writer_page.compress_content_streams(level=9)
        _optimize_pdf_resource_images(
            writer_page.get("/Resources"), seen_images, quality=image_quality
        )

    canonical_forms = {}
    fingerprint_cache = {}
    for page in writer.pages:
        _deduplicate_pdf_form_xobjects(
            page.get("/Resources"), canonical_forms, fingerprint_cache
        )
    _deduplicate_pdf_page_refs(writer)

    if hasattr(writer, "compress_identical_objects"):
        try:
            writer.compress_identical_objects(
                remove_duplicates=True,
                remove_unreferenced=True,
            )
        except TypeError:
            writer.compress_identical_objects(
                remove_identicals=True,
                remove_orphans=True,
            )

    buffer = BytesIO()
    writer.write(buffer)
    buffer.seek(0)

    compact_reader = PdfReader(buffer)
    compact_writer = PdfWriter()
    for page in compact_reader.pages:
        compact_writer.add_page(page)
    if hasattr(compact_writer, "compress_identical_objects"):
        try:
            compact_writer.compress_identical_objects(
                remove_duplicates=True,
                remove_unreferenced=True,
            )
        except TypeError:
            compact_writer.compress_identical_objects(
                remove_identicals=True,
                remove_orphans=True,
            )

    with open(output_path, "wb") as f:
        compact_writer.write(f)

    if len(PdfReader(output_path).pages) != len(reader.pages):
        raise ValueError("compressed PDF page count does not match source")


def compress_pdf(path):
    size_before = os.stat(path).st_size
    tmp = path + ".tmp"
    try:
        _write_pypdf_compressed(path, tmp, image_quality=80)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

    size_compressed = os.stat(tmp).st_size
    if size_compressed >= size_before:
        os.remove(tmp)
        print(
            f"compressed: skipped, {size_before // 1024}kb -> "
            f"{size_compressed // 1024}kb"
        )
        return

    os.replace(tmp, path)
    size_after = size_compressed
    print(
        f"compressed: {size_before // 1024}kb -> {size_after // 1024}kb ({round(size_after / size_before * 100)}%)"
    )


def optimize_raster_image_for_tex(path, quality=80):
    ext = os.path.splitext(path)[1].lower()
    if ext in VECTOR_IMAGE_EXTENSIONS:
        return path

    try:
        size_before = os.stat(path).st_size
    except OSError:
        return path

    try:
        with open(path, "rb") as source:
            optimized = optimize_raster_image_data(
                source.read(),
                original_extension=ext,
                quality=quality,
                exif_transpose=True,
            )
    except OSError:
        return path

    if optimized is None:
        return path

    optimized_extension, _, optimized_data = optimized
    fd, tmp = tempfile.mkstemp(suffix=f".{optimized_extension}")
    os.close(fd)
    with open(tmp, "wb") as output:
        output.write(optimized_data)

    if os.stat(tmp).st_size >= size_before:
        os.remove(tmp)
        return path
    return tmp


def read_file(filepath):
    with open(filepath, "r", encoding="utf8") as f:
        contents = f.read()
    return contents


def write_file(filepath, contents):
    with open(filepath, "w", encoding="utf8") as f:
        f.write(contents)


def replace_ext(filepath, new_ext):
    if not new_ext.startswith("."):
        new_ext = "." + new_ext
    dirname = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    base, _ = os.path.splitext(basename)
    return os.path.join(dirname, base + new_ext)


def wrap_val(key, val):
    if key in ("columns", "rows", "no_center", "color", "handouts_per_team"):
        return int(val.strip())
    if key in (
        "resize_image",
        "font_size",
        "tikz_mm",
        "hspace",
        "vspace",
        "max_width",
    ):
        return float(val.strip())
    if key == "grouping":
        val = val.strip().lower()
        if val not in ("horizontal", "vertical"):
            raise ValueError(
                f"Invalid grouping value: {val}. Must be 'horizontal' or 'vertical'."
            )
        return val
    if key == "rotate":
        val = val.strip().lower()
        if val not in ("r", "l"):
            raise ValueError(
                f"Invalid rotate value: {val}. Must be 'r' (right) or 'l' (left)."
            )
        return val
    return val.strip()


def split_array_by_value(arr, delimiter):
    result = []
    current_subarray = []
    for item in arr:
        if item == delimiter:
            result.append(current_subarray)
            current_subarray = []
        else:
            current_subarray.append(item)
    result.append(current_subarray)
    return result


def split_blocks(contents):
    lines = contents.split("\n")
    sp = ["\n".join(x) for x in split_array_by_value(lines, "---")]
    if not sp[0].strip():
        sp = sp[1:]
    return sp


def parse_handouts(contents):
    blocks = split_blocks(contents)
    result = []
    for block_ in blocks:
        block = block_.strip()
        block_dict = {}
        text = []
        lines = block.split("\n")
        for line in lines:
            sp = line.split(":", 1)
            if sp[0] in RESERVED_WORDS:
                block_dict[sp[0]] = wrap_val(sp[0], sp[1])
            elif line.strip():
                text.append(line.strip())
        if text:
            block_dict["text"] = "\n".join(text).strip()
            if not block_dict.get("raw_tex"):
                block_dict["text"] = escape_typst(block_dict["text"])
        result.append(block_dict)
    return result
