#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

FIELD_BY_MARKER = {
    "?": "question",
    "!": "answer",
    "=": "zachet",
    "!=": "nezachet",
    "/": "comment",
    "^": "source",
    "@": "author",
    ">": "handout",
    "№": "number",
    "№№": "setcounter",
}

QUESTION_SIDE_FIELDS = {"question", "handout"}
ANSWER_SIDE_FIELDS = {"answer", "zachet", "nezachet", "comment", "source", "author"}
SIDE_BY_FIELD = {
    **{field_name: "question" for field_name in QUESTION_SIDE_FIELDS},
    **{field_name: "answer" for field_name in ANSWER_SIDE_FIELDS},
}
QUESTION_START_FIELDS = {"question", "answer", "number", "setcounter"}
EXTENSION_BY_SUFFIX = {
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
    ".png": ".png",
}


class Rename4sImagesError(RuntimeError):
    pass


@dataclass
class ImageOccurrence:
    start: int
    end: int
    inner: str
    image_ref: str
    line_number: int
    field_name: str | None = None
    side: str | None = None
    question_number: int | None = None
    source_path: Path | None = None
    target_path: Path | None = None
    new_ref: str | None = None


@dataclass
class QuestionBlock:
    number_text: str | None = None
    setcounter_text: str | None = None
    occurrences: list[ImageOccurrence] = field(default_factory=list)
    question_number: int | None = None


@dataclass(frozen=True)
class RenamePlanItem:
    source_path: Path
    target_path: Path
    image_ref: str
    new_ref: str


@dataclass
class RenameResult:
    file_path: Path
    items: list[RenamePlanItem]
    dry_run: bool = False


def find_matching_closing_paren(text: str, index: int) -> int | None:
    level = 0
    for current_index in range(index, len(text)):
        if text[current_index] == "(":
            level += 1
        elif text[current_index] == ")":
            level -= 1
            if level == 0:
                return current_index
    return None


def _line_without_eol(line: str) -> str:
    return line.rstrip("\r\n")


def _line_marker(line: str) -> tuple[str | None, str]:
    line = _line_without_eol(line)
    stripped = line.lstrip()
    if not stripped:
        return None, ""
    parts = stripped.split(maxsplit=1)
    marker = parts[0]
    if marker not in FIELD_BY_MARKER:
        return None, ""
    marker_offset = len(line) - len(stripped)
    content = line[marker_offset + len(marker) :].strip()
    return marker, content


def _iter_img_tags(line: str, base_offset: int, line_number: int):
    i = 0
    while i < len(line):
        start = line.find("(img", i)
        if start == -1:
            return
        after_marker = start + len("(img")
        if after_marker < len(line) and not line[after_marker].isspace():
            i = after_marker
            continue
        end = find_matching_closing_paren(line, start)
        if end is None:
            raise Rename4sImagesError(
                f"Unclosed (img ...) tag on line {line_number}."
            )
        inner = line[after_marker:end].strip()
        image_ref = _parse_img_ref(inner, line_number)
        yield ImageOccurrence(
            start=base_offset + start,
            end=base_offset + end + 1,
            inner=inner,
            image_ref=image_ref,
            line_number=line_number,
        )
        i = end + 1


def _parse_img_ref(inner: str, line_number: int) -> str:
    try:
        parts = shlex.split(inner)
    except ValueError as exc:
        raise Rename4sImagesError(
            f"Cannot parse (img ...) tag on line {line_number}: {exc}."
        ) from exc
    if not parts:
        raise Rename4sImagesError(f"Empty (img ...) tag on line {line_number}.")
    return parts[-1]


def _replace_img_ref(inner: str, new_ref: str, line_number: int) -> str:
    try:
        parts = shlex.split(inner)
    except ValueError as exc:
        raise Rename4sImagesError(
            f"Cannot parse (img ...) tag on line {line_number}: {exc}."
        ) from exc
    parts[-1] = new_ref
    return f"(img {shlex.join(parts)})"


def _parse_int(text: str | None, context: str) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError as exc:
        raise Rename4sImagesError(f"Cannot use non-numeric {context}: {text!r}.") from exc


def _scan_4s(text: str) -> tuple[list[QuestionBlock], list[ImageOccurrence]]:
    blocks: list[QuestionBlock] = []
    orphan_occurrences: list[ImageOccurrence] = []
    current_block: QuestionBlock | None = None
    current_field: str | None = None
    offset = 0

    def finish_block():
        nonlocal current_block, current_field
        if current_block is not None:
            blocks.append(current_block)
        current_block = None
        current_field = None

    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        if not _line_without_eol(line).strip():
            finish_block()
            offset += len(line)
            continue

        marker, marker_content = _line_marker(line)
        field_name = FIELD_BY_MARKER.get(marker)
        if field_name is not None:
            if current_block is None and field_name in QUESTION_START_FIELDS:
                current_block = QuestionBlock()
            current_field = field_name if current_block is not None else None
            if current_block is not None and field_name == "number":
                current_block.number_text = marker_content
            elif current_block is not None and field_name == "setcounter":
                current_block.setcounter_text = marker_content

        occurrences = list(_iter_img_tags(line, offset, line_number))
        if occurrences:
            side = SIDE_BY_FIELD.get(current_field)
            if current_block is None or side is None:
                orphan_occurrences.extend(occurrences)
            else:
                for occurrence in occurrences:
                    occurrence.field_name = current_field
                    occurrence.side = side
                    current_block.occurrences.append(occurrence)

        offset += len(line)

    finish_block()
    return blocks, orphan_occurrences


def _assign_question_numbers(blocks: list[QuestionBlock]) -> None:
    counter = 1
    for block in blocks:
        setcounter = _parse_int(block.setcounter_text, "question counter")
        if setcounter is not None:
            counter = setcounter
        number = _parse_int(block.number_text, "question number")
        if number is None:
            number = counter
            counter += 1
        block.question_number = number
        for occurrence in block.occurrences:
            occurrence.question_number = number


def _resolve_image_path(image_ref: str, file_dir: Path) -> Path:
    if "://" in image_ref:
        raise Rename4sImagesError(
            f"Remote image cannot be renamed on disk: {image_ref!r}."
        )
    raw_path = Path(image_ref).expanduser()
    candidates = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.extend(
            [
                file_dir / raw_path,
                Path.cwd() / raw_path,
                file_dir / raw_path.name,
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise Rename4sImagesError(f"Image file not found: {image_ref!r}.")


def _new_ref_for_path(target_path: Path, file_dir: Path) -> str:
    try:
        return os.path.relpath(target_path, file_dir).replace(os.sep, "/")
    except ValueError:
        return str(target_path)


def _extension_for(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        return EXTENSION_BY_SUFFIX[suffix]
    except KeyError as exc:
        raise Rename4sImagesError(
            f"Unsupported image extension {path.suffix!r} for {path}."
        ) from exc


def _target_stem(question_number: int, side: str, sequence_number: int) -> str:
    stem = f"q{question_number}"
    if side == "answer":
        stem += "_answer"
    if sequence_number > 1:
        stem += f"_{sequence_number}"
    return stem


def _apply_width_to_stem(stem: str, question_number: int, width: int) -> str:
    padded_number = f"{question_number:0{width}d}"
    return "q" + padded_number + stem[len(f"q{question_number}") :]


def _build_plan(
    blocks: list[QuestionBlock], file_dir: Path, width: int | None
) -> tuple[list[ImageOccurrence], list[RenamePlanItem]]:
    occurrences = [occurrence for block in blocks for occurrence in block.occurrences]
    if not occurrences:
        return [], []

    numeric_questions = [
        block.question_number for block in blocks if block.question_number is not None
    ]
    if width is None:
        width = max(2, *(len(str(abs(number))) for number in numeric_questions))

    source_to_item: dict[Path, RenamePlanItem] = {}
    source_to_context: dict[Path, tuple[int, str]] = {}
    sequence_by_key: dict[tuple[int, str, str], int] = {}
    planned_items: list[RenamePlanItem] = []

    for occurrence in occurrences:
        if occurrence.question_number is None or occurrence.side is None:
            raise Rename4sImagesError(
                f"Image on line {occurrence.line_number} has no question number."
            )
        source_path = _resolve_image_path(occurrence.image_ref, file_dir)
        extension = _extension_for(source_path)
        existing_item = source_to_item.get(source_path)
        if existing_item is None:
            source_to_context[source_path] = (occurrence.question_number, occurrence.side)
            key = (occurrence.question_number, occurrence.side, extension)
            sequence_by_key[key] = sequence_by_key.get(key, 0) + 1
            stem = _target_stem(
                occurrence.question_number,
                occurrence.side,
                sequence_by_key[key],
            )
            target_name = (
                _apply_width_to_stem(stem, occurrence.question_number, width) + extension
            )
            target_path = source_path.with_name(target_name).resolve()
            new_ref = _new_ref_for_path(target_path, file_dir)
            existing_item = RenamePlanItem(
                source_path=source_path,
                target_path=target_path,
                image_ref=occurrence.image_ref,
                new_ref=new_ref,
            )
            source_to_item[source_path] = existing_item
            planned_items.append(existing_item)
        else:
            existing_context = source_to_context[source_path]
            current_context = (occurrence.question_number, occurrence.side)
            if existing_context != current_context:
                raise Rename4sImagesError(
                    f"Image {source_path} is used in multiple question contexts."
                )

        occurrence.source_path = source_path
        occurrence.target_path = existing_item.target_path
        occurrence.new_ref = existing_item.new_ref

    _check_target_collisions(planned_items)
    return occurrences, planned_items


def _check_target_collisions(items: list[RenamePlanItem]) -> None:
    source_paths = {item.source_path for item in items}
    target_to_source: dict[Path, Path] = {}
    for item in items:
        existing_source = target_to_source.get(item.target_path)
        if existing_source is not None and existing_source != item.source_path:
            raise Rename4sImagesError(
                f"Several images would be renamed to {item.target_path}."
            )
        target_to_source[item.target_path] = item.source_path
        if item.target_path.exists() and item.target_path not in source_paths:
            raise Rename4sImagesError(
                f"Target file already exists and is not part of this rename: "
                f"{item.target_path}."
            )


def _render_text(text: str, occurrences: list[ImageOccurrence]) -> str:
    if not occurrences:
        return text
    chunks = []
    last = 0
    for occurrence in sorted(occurrences, key=lambda item: item.start):
        if occurrence.new_ref is None:
            raise Rename4sImagesError(
                f"Internal error: missing replacement for line {occurrence.line_number}."
            )
        chunks.append(text[last : occurrence.start])
        chunks.append(
            _replace_img_ref(
                occurrence.inner, occurrence.new_ref, occurrence.line_number
            )
        )
        last = occurrence.end
    chunks.append(text[last:])
    return "".join(chunks)


def _rename_files(items: list[RenamePlanItem]) -> None:
    renames = [
        item for item in items if item.source_path.resolve() != item.target_path.resolve()
    ]
    if not renames:
        return

    tmp_by_item: list[tuple[RenamePlanItem, Path]] = []
    token = uuid.uuid4().hex
    try:
        for index, item in enumerate(renames):
            tmp_path = item.source_path.with_name(
                f".{item.source_path.name}.rename-4s-{token}-{index}.tmp"
            )
            item.source_path.rename(tmp_path)
            tmp_by_item.append((item, tmp_path))
        for item, tmp_path in tmp_by_item:
            tmp_path.rename(item.target_path)
    except Exception:
        _rollback_file_renames(tmp_by_item)
        raise


def _rollback_file_renames(tmp_by_item: list[tuple[RenamePlanItem, Path]]) -> None:
    for item, tmp_path in reversed(tmp_by_item):
        try:
            if tmp_path.exists() and not item.source_path.exists():
                tmp_path.rename(item.source_path)
            elif item.target_path.exists() and not item.source_path.exists():
                item.target_path.rename(item.source_path)
        except OSError:
            pass


def rename_4s_images(
    file_path: str | Path, *, dry_run: bool = False, width: int | None = None
) -> RenameResult:
    path = Path(file_path).resolve()
    if width is not None and width < 1:
        raise Rename4sImagesError("--width must be at least 1.")
    text = path.read_text(encoding="utf-8")
    blocks, orphan_occurrences = _scan_4s(text)
    if orphan_occurrences:
        lines = ", ".join(str(item.line_number) for item in orphan_occurrences)
        raise Rename4sImagesError(
            f"Found (img ...) tag outside a question field on line(s): {lines}."
        )
    _assign_question_numbers(blocks)
    occurrences, items = _build_plan(blocks, path.parent, width)
    new_text = _render_text(text, occurrences)

    if not dry_run:
        backup_path = path.with_name(f".{path.name}.rename-4s-backup")
        shutil.copy2(path, backup_path)
        try:
            _rename_files(items)
            path.write_text(new_text, encoding="utf-8")
        except Exception:
            if backup_path.exists():
                shutil.copy2(backup_path, path)
            raise
        finally:
            backup_path.unlink(missing_ok=True)

    return RenameResult(file_path=path, items=items, dry_run=dry_run)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rename local jpg/png images referenced by (img ...) tags in a 4s file "
            "to qNN.ext or qNN_answer.ext and update the file in place."
        )
    )
    parser.add_argument("filename", help="4s file to update")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned renames without changing files",
    )
    parser.add_argument(
        "--width",
        type=int,
        help="zero-padding width; by default uses at least 2 digits",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        result = rename_4s_images(args.filename, dry_run=args.dry_run, width=args.width)
    except Rename4sImagesError as exc:
        parser.error(str(exc))
    action = "Would rename" if result.dry_run else "Renamed"
    print(f"{action} {len(result.items)} image(s) for {result.file_path}.")
    for item in result.items:
        print(f"{item.source_path} -> {item.target_path}")
    return 0


def _touch_image(path: Path):
    path.write_bytes(b"image")


def _assert_raises_contains(exc_type, message_part, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except exc_type as exc:
        assert message_part in str(exc)
    else:
        raise AssertionError(f"{exc_type.__name__} was not raised")


def test_rename_4s_images_question_and_answer_fields(tmp_path):
    _touch_image(tmp_path / "question.jpg")
    _touch_image(tmp_path / "answer.png")
    _touch_image(tmp_path / "comment.jpeg")
    packet = tmp_path / "packet.4s"
    packet.write_text(
        "? text (img question.jpg)\n"
        "! answer (img answer.png)\n"
        "/ comment (img comment.jpeg)\n",
        encoding="utf-8",
    )

    result = rename_4s_images(packet)

    assert [item.target_path.name for item in result.items] == [
        "q01.jpg",
        "q01_answer.png",
        "q01_answer.jpg",
    ]
    assert packet.read_text(encoding="utf-8") == (
        "? text (img q01.jpg)\n"
        "! answer (img q01_answer.png)\n"
        "/ comment (img q01_answer.jpg)\n"
    )
    assert (tmp_path / "q01.jpg").is_file()
    assert (tmp_path / "q01_answer.png").is_file()
    assert (tmp_path / "q01_answer.jpg").is_file()
    assert not (tmp_path / "question.jpg").exists()
    assert not (tmp_path / "answer.png").exists()
    assert not (tmp_path / "comment.jpeg").exists()


def test_rename_4s_images_padding_setcounter_and_multiple_same_ext(tmp_path):
    for name in ("first.jpg", "second.jpg", "third.png", "fourth.jpeg"):
        _touch_image(tmp_path / name)
    packet = tmp_path / "packet.4s"
    packet.write_text(
        "№№ 9\n"
        "? first (img first.jpg) and (img second.jpg)\n"
        "! answer\n"
        "\n"
        "? second (img third.png)\n"
        "! answer (img fourth.jpeg)\n",
        encoding="utf-8",
    )

    rename_4s_images(packet)

    assert packet.read_text(encoding="utf-8") == (
        "№№ 9\n"
        "? first (img q09.jpg) and (img q09_2.jpg)\n"
        "! answer\n"
        "\n"
        "? second (img q10.png)\n"
        "! answer (img q10_answer.jpg)\n"
    )
    for name in ("q09.jpg", "q09_2.jpg", "q10.png", "q10_answer.jpg"):
        assert (tmp_path / name).is_file()


def test_rename_4s_images_reuses_same_source_in_same_context(tmp_path):
    _touch_image(tmp_path / "same.jpg")
    packet = tmp_path / "packet.4s"
    packet.write_text(
        "? text (img same.jpg) and again (img same.jpg)\n! answer\n",
        encoding="utf-8",
    )

    result = rename_4s_images(packet)

    assert len(result.items) == 1
    assert packet.read_text(encoding="utf-8") == (
        "? text (img q01.jpg) and again (img q01.jpg)\n! answer\n"
    )
    assert (tmp_path / "q01.jpg").is_file()


def test_rename_4s_images_dry_run_does_not_change_files(tmp_path):
    _touch_image(tmp_path / "question.jpg")
    packet = tmp_path / "packet.4s"
    original_text = "? text (img question.jpg)\n! answer\n"
    packet.write_text(original_text, encoding="utf-8")

    result = rename_4s_images(packet, dry_run=True)

    assert result.dry_run
    assert [item.target_path.name for item in result.items] == ["q01.jpg"]
    assert packet.read_text(encoding="utf-8") == original_text
    assert (tmp_path / "question.jpg").is_file()
    assert not (tmp_path / "q01.jpg").exists()


def test_rename_4s_images_does_not_overwrite_existing_target(tmp_path):
    _touch_image(tmp_path / "question.jpg")
    _touch_image(tmp_path / "q01.jpg")
    packet = tmp_path / "packet.4s"
    packet.write_text("? text (img question.jpg)\n! answer\n", encoding="utf-8")

    _assert_raises_contains(
        Rename4sImagesError,
        "Target file already exists",
        rename_4s_images,
        packet,
    )

    assert (tmp_path / "question.jpg").is_file()
    assert (tmp_path / "q01.jpg").is_file()
    assert packet.read_text(encoding="utf-8") == "? text (img question.jpg)\n! answer\n"


def test_rename_4s_images_rejects_images_outside_question_fields(tmp_path):
    _touch_image(tmp_path / "meta.jpg")
    packet = tmp_path / "packet.4s"
    packet.write_text("# meta (img meta.jpg)\n", encoding="utf-8")

    _assert_raises_contains(
        Rename4sImagesError,
        "outside a question field",
        rename_4s_images,
        packet,
    )


if __name__ == "__main__":
    raise SystemExit(main())
