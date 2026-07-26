"""Tests for handouter layout detection algorithm."""

import os
import random
import subprocess
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from chgksuite.handouter import utils as handouter_utils
from chgksuite.handouter.runner import HandoutGenerator, process_file
from chgksuite.handouter.split_fit import (
    HandoutBlock,
    all_q_block_text,
    parse_blocks,
    split_fit_columns,
    write_handout,
)
from chgksuite.handouter.utils import (
    optimize_raster_image_for_tex,
    parse_handouts,
    wrap_val,
)


@pytest.fixture
def generator():
    """Create a HandoutGenerator with minimal mock args."""
    args = Mock()
    args.language = "ru"
    args.paperwidth = 210
    args.paperheight = 297
    args.margin_left = 5
    args.margin_right = 5
    args.margin_top = 5
    args.margin_bottom = 5
    args.tikz_mm = 1
    args.font = None
    args.font_size = 12
    args.boxwidth = None
    args.boxwidthinner = None
    args.debug = False
    args.optimize_images = "on"
    return HandoutGenerator(args)


def write_noisy_png(path, size=(96, 96)):
    rng = random.Random(1)
    image = Image.new("RGB", size)
    image.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(size[0] * size[1])
        ]
    )
    image.save(path, format="PNG")


class TestGetCutDirection:
    """Tests for the get_cut_direction method."""

    def test_single_team_1x3(self, generator):
        """1 column × 3 rows with 3 handouts/team = 1 team rectangle."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=1, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 1
        assert team_rows == 3

    def test_single_team_3x1(self, generator):
        """3 columns × 1 row with 3 handouts/team = 1 team rectangle."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=1, handouts_per_team=3
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_3x3_prefers_horizontal(self, generator):
        """3×3 grid can be grouped as 3×1 or 1×3, should prefer horizontal (3×1)."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3
        )
        # Horizontal grouping: 3 columns × 1 row per team
        assert team_cols == 3
        assert team_rows == 1

    def test_2x6_vertical_grouping(self, generator):
        """2 columns × 6 rows with 3 handouts/team = 4 teams of 1×3."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=2, num_rows=6, handouts_per_team=3
        )
        # Only valid option: 1 column × 3 rows per team
        assert team_cols == 1
        assert team_rows == 3

    def test_6x3_prefers_horizontal(self, generator):
        """6×3 grid can be 3×1 or 1×3, should prefer horizontal (3×1)."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_4x3_vertical_only(self, generator):
        """4 columns × 3 rows with 3 handouts/team = vertical grouping only."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=4, num_rows=3, handouts_per_team=3
        )
        # 4 columns can't be divided by 3, so only 1×3 works
        assert team_cols == 1
        assert team_rows == 3

    def test_2x3_vertical_grouping(self, generator):
        """2 columns × 3 rows with 3 handouts/team = 2 teams of 1×3."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=2, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 1
        assert team_rows == 3

    def test_invalid_not_divisible(self, generator):
        """Total handouts not divisible by handouts_per_team returns None."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=2, num_rows=2, handouts_per_team=3
        )
        # 4 total handouts, can't divide by 3
        assert team_cols is None
        assert team_rows is None

    def test_invalid_no_valid_layout(self, generator):
        """Grid dimensions don't allow valid team rectangles."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=5, num_rows=5, handouts_per_team=3
        )
        # 25 total, not divisible by 3
        assert team_cols is None
        assert team_rows is None

    def test_handouts_per_team_1(self, generator):
        """Each cell is its own team (handouts_per_team=1)."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=1
        )
        assert team_cols == 1
        assert team_rows == 1

    def test_handouts_per_team_equals_total(self, generator):
        """All cells form one team."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=9
        )
        assert team_cols == 3
        assert team_rows == 3

    def test_4x6_with_6_per_team(self, generator):
        """4×6 grid with 6 handouts/team can be 2×3 or 3×2, prefers 3×2."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=4, num_rows=6, handouts_per_team=6
        )
        # 4%2=0, 6%3=0 -> (2, 3)
        # 4%3≠0 -> (3, 2) invalid
        # Only option is (2, 3)
        assert team_cols == 2
        assert team_rows == 3

    def test_6x4_with_6_per_team_prefers_horizontal(self, generator):
        """6×4 grid with 6 handouts/team, picks most horizontal option."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=4, handouts_per_team=6
        )
        # Valid options: (6, 1) and (3, 2)
        # (6, 1): 6%6=0, 4%1=0 valid
        # (3, 2): 6%3=0, 4%2=0 valid
        # (2, 3): 6%2=0, 4%3≠0 invalid
        # Prefer smallest team_rows -> (6, 1)
        assert team_cols == 6
        assert team_rows == 1

    def test_6x6_with_6_per_team(self, generator):
        """6×6 grid with 6 handouts/team, multiple options, prefers horizontal."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=6, handouts_per_team=6
        )
        # Valid options: (6, 1), (3, 2), (2, 3), (1, 6)
        # Sorted by team_rows: [(6, 1), (3, 2), (2, 3), (1, 6)]
        # Pick (6, 1) - most horizontal
        assert team_cols == 6
        assert team_rows == 1


class TestGroupingPreference:
    """Tests for the grouping preference option."""

    def test_3x3_default_horizontal(self, generator):
        """3×3 grid defaults to horizontal grouping."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_3x3_explicit_horizontal(self, generator):
        """3×3 grid with explicit horizontal grouping."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3, grouping="horizontal"
        )
        assert team_cols == 3
        assert team_rows == 1

    def test_3x3_vertical_grouping(self, generator):
        """3×3 grid with vertical grouping preference."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=3, num_rows=3, handouts_per_team=3, grouping="vertical"
        )
        # Vertical: prefer smaller team_cols -> 1×3 teams
        assert team_cols == 1
        assert team_rows == 3

    def test_6x6_default_horizontal(self, generator):
        """6×6 grid with 6 handouts/team defaults to horizontal."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=6, handouts_per_team=6
        )
        # Options: (6,1), (3,2), (2,3), (1,6)
        # Horizontal prefers smallest team_rows -> (6, 1)
        assert team_cols == 6
        assert team_rows == 1

    def test_6x6_vertical_grouping(self, generator):
        """6×6 grid with 6 handouts/team and vertical preference."""
        team_cols, team_rows = generator.get_cut_direction(
            columns=6, num_rows=6, handouts_per_team=6, grouping="vertical"
        )
        # Options: (6,1), (3,2), (2,3), (1,6)
        # Vertical prefers smallest team_cols -> (1, 6)
        assert team_cols == 1
        assert team_rows == 6

    def test_grouping_only_one_option(self, generator):
        """When only one layout is valid, grouping preference doesn't matter."""
        # 2×6 with 3 handouts/team: only (1, 3) is valid
        team_cols_h, team_rows_h = generator.get_cut_direction(
            columns=2, num_rows=6, handouts_per_team=3, grouping="horizontal"
        )
        team_cols_v, team_rows_v = generator.get_cut_direction(
            columns=2, num_rows=6, handouts_per_team=3, grouping="vertical"
        )
        assert team_cols_h == team_cols_v == 1
        assert team_rows_h == team_rows_v == 3


class TestGroupingParsing:
    """Tests for parsing the grouping option from txt files."""

    def test_parse_grouping_horizontal(self):
        """Parse horizontal grouping option."""
        contents = """for_question: 1
columns: 3
rows: 3
grouping: horizontal
test"""
        result = parse_handouts(contents)
        assert result[0]["grouping"] == "horizontal"

    def test_parse_grouping_vertical(self):
        """Parse vertical grouping option."""
        contents = """for_question: 1
columns: 3
rows: 3
grouping: vertical
test"""
        result = parse_handouts(contents)
        assert result[0]["grouping"] == "vertical"

    def test_parse_grouping_case_insensitive(self):
        """Grouping option should be case insensitive."""
        contents = """columns: 3
grouping: VERTICAL
test"""
        result = parse_handouts(contents)
        assert result[0]["grouping"] == "vertical"

    def test_parse_no_grouping_defaults_none(self):
        """When grouping is not specified, it should not be in the dict."""
        contents = """columns: 3
rows: 3
test"""
        result = parse_handouts(contents)
        assert "grouping" not in result[0]

    def test_parse_max_width(self):
        """Parse max_width as a floating-point metadata value."""
        contents = """columns: 3
max_width: 0.5
test"""
        result = parse_handouts(contents)
        assert result[0]["max_width"] == 0.5
        assert "max_width" not in result[0]["text"]

    def test_split_fit_parse_max_width_as_metadata(self):
        """split_fit should preserve max_width as metadata, not handout text."""
        contents = """columns: 3
max_width: 0.5
test"""
        result = parse_blocks(contents)
        assert result[0].meta["max_width"] == "0.5"

    def test_wrap_val_grouping_invalid(self):
        """Invalid grouping value should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid grouping value"):
            wrap_val("grouping", "diagonal")


class TestMaxWidthLayout:
    def test_max_width_limits_auto_box_width(self, generator):
        typst = generator.generate_regular_block(
            {"columns": 3, "rows": 1, "max_width": 0.5, "text": "test"}
        )

        # available width = page width (198mm) * 0.5 = 99mm; one team (3x1) so no
        # between-team gaps -> cellw = 99 / 3 = 33mm.
        assert "#handout(3, 1, 3, 1, 1.5mm, 33.0mm, 1mm, 5.08mm, true, true," in typst
        assert "[test]" in typst

    def test_invalid_max_width_raises(self, generator):
        with pytest.raises(ValueError, match="max_width must be between 0 and 1"):
            generator.generate_regular_block(
                {"columns": 3, "max_width": 1.5, "text": "test"}
            )

    def test_generate_keeps_question_label_with_handout_grid(self, generator):
        generator.args.filename = "handouts.hndt"
        generator.parse_input = lambda filename: [
            {"for_question": 18, "columns": 3, "text": "test"}
        ]

        typst = generator.generate()

        # The grey label is emitted directly above its handout block.
        assert "#qlabel[" in typst
        assert "#handout(" in typst
        assert typst.index("#qlabel[") < typst.index("#handout(")
        # The sticky label keeps glued to its block across page breaks.
        assert "sticky: true" in typst

    def test_generate_keeps_question_label_without_handout_grid(self, generator):
        generator.args.filename = "handouts.hndt"
        generator.parse_input = lambda filename: [{"for_question": 18}]

        typst = generator.generate()

        # No grid: the label stands alone, no handout block is emitted.
        assert "#qlabel[" in typst
        assert "#handout(" not in typst

    def test_split_fit_multiplies_half_width_columns(self, tmp_path):
        block = HandoutBlock(
            ordinal=1,
            text="columns: 3\nmax_width: 0.5\n\nhandout",
            meta={"columns": "3", "max_width": "0.5"},
        )
        output_path = tmp_path / "out.hndt"

        write_handout(block, output_path, rows=4, source_dir=tmp_path)

        contents = output_path.read_text(encoding="utf8")
        assert split_fit_columns(block) == 6
        assert "columns: 6" in contents
        assert "rows: 4" in contents
        assert "max_width:" not in contents

    def test_split_fit_all_q_keeps_half_width_for_one_team_mode(self, tmp_path):
        block = HandoutBlock(
            ordinal=1,
            text="columns: 3\nmax_width: 0.5\n\nhandout",
            meta={"columns": "3", "max_width": "0.5"},
        )

        contents = all_q_block_text(block, tmp_path, tmp_path, None)

        assert "columns: 3" in contents
        assert "max_width: 0.5" in contents
        assert "rows: 1" in contents


def test_optimize_raster_image_for_tex_recompresses_png(tmp_path):
    image_path = tmp_path / "handout.png"
    write_noisy_png(image_path)

    optimized_path = optimize_raster_image_for_tex(str(image_path), quality=80)

    try:
        assert optimized_path != str(image_path)
        assert optimized_path.endswith(".jpg")
        assert (tmp_path / "handout.png").stat().st_size > 0
        with open(optimized_path, "rb") as optimized:
            assert optimized.read(2) == b"\xff\xd8"
        assert os.stat(optimized_path).st_size < image_path.stat().st_size
    finally:
        if optimized_path != str(image_path):
            os.remove(optimized_path)


def test_optimize_raster_image_for_tex_skips_vectors(tmp_path):
    image_path = tmp_path / "handout.svg"
    image_path.write_text("<svg></svg>", encoding="utf8")

    assert optimize_raster_image_for_tex(str(image_path), quality=80) == str(image_path)


def test_optimize_raster_image_for_tex_keeps_smaller_original(tmp_path):
    image_path = tmp_path / "tiny.png"
    Image.new("RGB", (1, 1), (255, 255, 255)).save(image_path, format="PNG")

    assert optimize_raster_image_for_tex(str(image_path), quality=80) == str(image_path)


def test_optimize_raster_image_for_tex_preserves_transparent_png(tmp_path):
    image_path = tmp_path / "transparent.png"
    Image.new("RGBA", (96, 96), (255, 0, 0, 128)).save(
        image_path, format="PNG", compress_level=0
    )

    optimized_path = optimize_raster_image_for_tex(str(image_path), quality=80)

    try:
        assert optimized_path.endswith(".png")
        with Image.open(optimized_path) as image:
            assert image.convert("RGBA").getchannel("A").getextrema()[0] < 255
    finally:
        if optimized_path != str(image_path):
            os.remove(optimized_path)


def test_recompress_pdf_image_converts_raw_rgb_to_smaller_jpeg():
    image = Image.new("RGB", (96, 96))
    rng = random.Random(2)
    image.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(96 * 96)
        ]
    )
    raw_data = image.tobytes()

    stream = DecodedStreamObject()
    stream.set_data(raw_data)
    stream[NameObject("/Subtype")] = NameObject("/Image")
    stream[NameObject("/Width")] = NumberObject(96)
    stream[NameObject("/Height")] = NumberObject(96)
    stream[NameObject("/BitsPerComponent")] = NumberObject(8)
    stream[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")

    assert handouter_utils._recompress_pdf_image(stream, quality=80)
    assert stream["/Filter"] == "/DCTDecode"
    assert stream["/ColorSpace"] == "/DeviceRGB"
    assert len(stream._data) < len(raw_data)


def test_recompress_pdf_image_handles_indexed_palette_text_string():
    raw_data = bytes([0, 1, 0, 1]) * (96 * 96 // 4)

    stream = DecodedStreamObject()
    stream.set_data(raw_data)
    stream[NameObject("/Subtype")] = NameObject("/Image")
    stream[NameObject("/Width")] = NumberObject(96)
    stream[NameObject("/Height")] = NumberObject(96)
    stream[NameObject("/BitsPerComponent")] = NumberObject(8)
    stream[NameObject("/ColorSpace")] = ArrayObject(
        [
            NameObject("/Indexed"),
            NameObject("/DeviceRGB"),
            NumberObject(1),
            TextStringObject("\xff\x00\x00\x00\x00\xff"),
        ]
    )

    assert handouter_utils._recompress_pdf_image(stream, quality=80)
    assert stream["/Filter"] == "/DCTDecode"
    assert stream["/ColorSpace"] == "/DeviceRGB"


def test_write_pypdf_compressed_deduplicates_repeated_form_xobjects(tmp_path):
    source_pdf = tmp_path / "source.pdf"
    compressed_pdf = tmp_path / "compressed.pdf"
    writer = PdfWriter()

    for _ in range(2):
        page = writer.add_blank_page(width=200, height=200)
        form = DecodedStreamObject()
        form.set_data(b"0 0 20 20 re f\n")
        form[NameObject("/Type")] = NameObject("/XObject")
        form[NameObject("/Subtype")] = NameObject("/Form")
        form[NameObject("/BBox")] = ArrayObject(
            [NumberObject(0), NumberObject(0), NumberObject(20), NumberObject(20)]
        )
        form_ref = writer._add_object(form)
        resources_ref = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/XObject"): DictionaryObject(
                        {NameObject("/Fm0"): form_ref}
                    )
                }
            )
        )
        page[NameObject("/Resources")] = resources_ref
        stream = DecodedStreamObject()
        stream.set_data(b"q 1 0 0 1 10 10 cm /Fm0 Do Q\n")
        page[NameObject("/Contents")] = writer._add_object(stream)

    with open(source_pdf, "wb") as output:
        writer.write(output)

    handouter_utils._write_pypdf_compressed(str(source_pdf), str(compressed_pdf))

    form_refs = []
    resource_refs = []
    reader = PdfReader(str(compressed_pdf))
    for page in reader.pages:
        resource_refs.append(page.raw_get("/Resources").idnum)
        xobjects = page["/Resources"].raw_get("/XObject").get_object()
        form_refs.append(xobjects.raw_get("/Fm0").idnum)

    assert len(set(form_refs)) == 1
    assert len(set(resource_refs)) == 1


def test_handout_generator_uses_optimized_image_path(generator, tmp_path):
    image_path = tmp_path / "handout.png"
    write_noisy_png(image_path)
    generator.input_dir = str(tmp_path)

    tex = generator.generate_regular_block({"image": "handout.png", "columns": 1})

    try:
        assert "handout.png" not in tex
        assert any(path.endswith(".jpg") for path in generator._temp_files)
    finally:
        for path in generator._temp_files:
            os.remove(path)


def test_handout_generator_normalizes_windows_temp_image_path(generator, monkeypatch):
    windows_temp_path = (
        "C:\\Users\\USER~1\\AppData\\Local\\Temp\\2\\tmpigabk_hf.jpg"
    )

    def fake_optimize_raster_image_for_tex(path, quality=80):
        return windows_temp_path

    monkeypatch.setattr(
        "chgksuite.handouter.runner.optimize_raster_image_for_tex",
        fake_optimize_raster_image_for_tex,
    )

    typst = generator.generate_regular_block({"image": "handout.png", "columns": 1})

    assert (
        'image("C:/Users/USER~1/AppData/Local/Temp/2/tmpigabk_hf.jpg", width: 100.0%)'
        in typst
    )
    assert windows_temp_path not in typst


def test_handout_generator_can_disable_image_optimization(generator, tmp_path):
    image_path = tmp_path / "handout.png"
    write_noisy_png(image_path)
    generator.optimize_images = False

    tex = generator.generate_regular_block({"image": str(image_path), "columns": 1})

    assert str(image_path) in tex
    assert not generator._temp_files


def test_process_file_replays_typst_output_on_failure(
    tmp_path, monkeypatch, capsys
):
    class FakeGenerator:
        _temp_files: ClassVar[list] = []

        def __init__(self, args):
            self.args = args

        def generate(self):
            return "#pagebreak()"

    def fake_run(cmd, check, cwd, text, capture_output):
        assert check is False
        assert text is True
        assert capture_output is True
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="typst stdout\n",
            stderr="unexpected end of block\n",
        )

    hndt_path = tmp_path / "handout.hndt"
    hndt_path.write_text("columns: 1\ntext", encoding="utf8")
    args = SimpleNamespace(
        filename=str(hndt_path),
        language="ru",
        add_n_teams="off",
        compress_pdf="off",
        debug=False,
    )
    monkeypatch.setattr("chgksuite.handouter.runner.HandoutGenerator", FakeGenerator)
    monkeypatch.setattr("chgksuite.handouter.runner.get_typst_path", lambda: "typst")
    monkeypatch.setattr("chgksuite.handouter.runner.subprocess.run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        process_file(args, str(tmp_path), "handout")

    captured = capsys.readouterr()
    assert "typst stdout" in captured.out
    assert "unexpected end of block" in captured.err


def test_compress_pdf_keeps_original_when_compressed_file_is_larger(
    tmp_path, monkeypatch, capsys
):
    pdf_path = tmp_path / "handout.pdf"
    original = b"small pdf"
    pdf_path.write_bytes(original)

    def fake_write_compressed(input_path, output_path, image_quality=80):
        assert input_path == str(pdf_path)
        assert image_quality == 80
        with open(output_path, "wb") as output:
            output.write(b"larger compressed pdf")

    monkeypatch.setattr(
        handouter_utils, "_write_pypdf_compressed", fake_write_compressed
    )
    handouter_utils.compress_pdf(str(pdf_path))

    assert pdf_path.read_bytes() == original
    assert not os.path.exists(str(pdf_path) + ".tmp")
    assert "skipped" in capsys.readouterr().out


def test_compress_pdf_replaces_original_when_compressed_file_is_smaller(
    tmp_path, monkeypatch
):
    pdf_path = tmp_path / "handout.pdf"
    pdf_path.write_bytes(b"x" * 100)

    def fake_write_compressed(input_path, output_path, image_quality=80):
        with open(output_path, "wb") as output:
            output.write(b"small")

    monkeypatch.setattr(
        handouter_utils, "_write_pypdf_compressed", fake_write_compressed
    )
    handouter_utils.compress_pdf(str(pdf_path))

    assert pdf_path.read_bytes() == b"small"


def test_measure_handout_parses_typst_query(tmp_path, monkeypatch):
    from chgksuite.handouter import split_fit

    hndt_path = tmp_path / "q.hndt"
    hndt_path.write_text("columns: 3\nrows: 5\ntext: hi\n", encoding="utf8")

    monkeypatch.setattr(split_fit, "cached_typst_path", lambda _renderer_args: "typst")
    monkeypatch.setattr(
        split_fit.HandoutGenerator, "generate", lambda self: "// handout body"
    )

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(
            returncode=0,
            stdout='{"pages": 1, "y_mm": 197.0}',
            stderr="",
        )

    monkeypatch.setattr(split_fit.subprocess, "run", fake_run)

    args = SimpleNamespace(language="ru", paperheight=297)
    result = split_fit.measure_handout(hndt_path, args)

    assert result.ok
    assert result.pages == 1
    assert result.fits_one_page
    # bottom space = paperheight - y_mm
    assert result.bottom_space_mm == pytest.approx(100.0)
    # typst paginates the document itself: a query, not a PDF compile.
    assert "query" in captured["cmd"]
    # the measurement .typ is cleaned up
    assert not (tmp_path / "q_measure.typ").exists()


def test_measure_handout_reports_overflow_without_bottom_space(tmp_path, monkeypatch):
    from chgksuite.handouter import split_fit

    hndt_path = tmp_path / "q.hndt"
    hndt_path.write_text("columns: 3\nrows: 50\ntext: hi\n", encoding="utf8")

    monkeypatch.setattr(split_fit, "cached_typst_path", lambda _renderer_args: "typst")
    monkeypatch.setattr(
        split_fit.HandoutGenerator, "generate", lambda self: "// handout body"
    )
    monkeypatch.setattr(
        split_fit.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(
            returncode=0, stdout='{"pages": 2, "y_mm": 50.0}', stderr=""
        ),
    )

    args = SimpleNamespace(language="ru", paperheight=297)
    result = split_fit.measure_handout(hndt_path, args)

    assert result.pages == 2
    assert not result.fits_one_page
    assert result.bottom_space_mm is None
