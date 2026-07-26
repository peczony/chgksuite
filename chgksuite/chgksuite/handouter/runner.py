import os
import subprocess
import sys
import tempfile
import time

import toml
from PIL import Image
from pypdf import PdfReader, PdfWriter
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from chgksuite.common import ChgksuiteError, get_source_dirs, set_lastdir
from chgksuite.handouter.gen import generate_handouts
from chgksuite.handouter.installer import (
    get_bundled_fonts_dir,
    get_typst_path,
    install_typst,
)
from chgksuite.handouter.pack import pack_handouts
from chgksuite.handouter.typst_internals import (
    GREYTEXT,
    HEADER,
    IMG,
    IMGWIDTH,
)
from chgksuite.handouter.utils import (
    compress_pdf,
    optimize_raster_image_for_tex,
    parse_handouts,
    read_file,
    replace_ext,
    write_file,
)


def tex_image_path(image_path):
    return str(image_path).replace("\\", "/")


def rotate_image(image_path, direction):
    """Rotate an image or PDF 90 degrees and save to a temp file.
    direction: 'r' for right (clockwise), 'l' for left (counter-clockwise).
    Returns the path to the rotated temp file.
    """
    ext = os.path.splitext(image_path)[1].lower() or ".png"

    if ext == ".pdf":
        reader = PdfReader(image_path)
        writer = PdfWriter()
        angle = 270 if direction == "r" else 90
        for page in reader.pages:
            page.rotate(angle)
            writer.add_page(page)
        fd, tmp_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        with open(tmp_path, "wb") as f:
            writer.write(f)
        return tmp_path

    img = Image.open(image_path)
    # PIL's rotate is counter-clockwise, so right = -90, left = 90
    angle = -90 if direction == "r" else 90
    rotated = img.rotate(angle, expand=True)
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    rotated.save(tmp_path)
    return tmp_path


DEFAULT_FONT = "Noto Sans"


class HandoutGenerator:
    SPACE = 1.5  # mm
    DEFAULT_TIKZ_MM = 2  # mm

    def __init__(self, args):
        self.args = args
        self._temp_files = []
        self.optimize_images = getattr(args, "optimize_images", "on") == "on"
        filename = getattr(args, "filename", None)
        if not isinstance(filename, (str, bytes, os.PathLike)):
            filename = None
        self.input_dir = (
            os.path.dirname(os.path.abspath(filename)) if filename else os.getcwd()
        )
        _, resourcedir = get_source_dirs()
        self.labels = toml.loads(
            read_file(os.path.join(resourcedir, f"labels_{args.language}.toml"))
        )
        self.blocks = [self.get_header()]

    # The grey label's gaps (large above to separate questions, tiny below so it
    # hugs its grid), in millimetres.
    LABEL_ABOVE = 2.0
    LABEL_BELOW = 0.6
    # A short single line fills a cell of this height per em of font size (the
    # old TeX `\vphantom{Ayg}` strut + baseline skip), so cells line up.
    STRUT_EM = 1.2

    def get_header(self):
        header = HEADER
        header = (
            header.replace("<PAPERWIDTH>", str(self.args.paperwidth))
            .replace("<PAPERHEIGHT>", str(self.args.paperheight))
            .replace("<MARGIN_LEFT>", str(self.args.margin_left))
            .replace("<MARGIN_RIGHT>", str(self.args.margin_right))
            .replace("<MARGIN_TOP>", str(self.args.margin_top))
            .replace("<MARGIN_BOTTOM>", str(self.args.margin_bottom))
            .replace("<FONT>", self.args.font or DEFAULT_FONT)
            .replace("<FONTSIZE>", str(self.args.font_size))
            .replace("<LABEL_ABOVE>", str(self.LABEL_ABOVE))
            .replace("<LABEL_BELOW>", str(self.LABEL_BELOW))
        )
        return header

    def effective_tikz_mm(self, block):
        """Cell inset in mm: a global override wins, then the per-block value,
        else the default (the old TikZ ``inner sep``)."""
        if self.args.tikz_mm is not None:
            return self.args.tikz_mm
        if block.get("tikz_mm") is not None:
            return block["tikz_mm"]
        return self.DEFAULT_TIKZ_MM

    def parse_input(self, filepath):
        contents = read_file(filepath)
        return parse_handouts(contents)

    def generate_for_question(self, question_num):
        handout_text = self.labels["general"]["handout_for_question"].format(
            question_num
        )
        return GREYTEXT.replace("<GREYTEXT>", handout_text)

    def wrap_question_block(self, label, grid):
        """Join a question's grey label and its handout block.

        The label (a ``#qlabel`` sticky block) already carries its own spacing
        and stays glued to the block below it across page breaks.
        """
        return "\n\n".join(p for p in (label, grid) if p)

    def get_page_width(self):
        return self.args.paperwidth - self.args.margin_left - self.args.margin_right - 2

    def get_block_max_width(self, block):
        max_width = block.get("max_width", 1.0)
        if max_width <= 0 or max_width > 1:
            raise ValueError(f"max_width must be between 0 and 1, got {max_width}")
        return max_width

    def resolve_image_path(self, image_path):
        if os.path.isabs(image_path):
            return image_path
        return os.path.join(self.input_dir, image_path)

    def prepare_image(self, image_path):
        if not self.optimize_images:
            return image_path
        source_path = self.resolve_image_path(image_path)
        optimized_path = optimize_raster_image_for_tex(source_path, quality=80)
        if optimized_path != source_path:
            self._temp_files.append(optimized_path)
            return optimized_path
        return image_path

    def get_cut_direction(
        self, columns, num_rows, handouts_per_team, grouping="horizontal"
    ):
        """
        Determine team rectangle dimensions.
        Returns (team_cols, team_rows) where each team is a team_cols × team_rows block.

        Falls back to (None, None) if handouts can't be evenly divided into teams.

        Args:
            grouping: "horizontal" (default) prefers wider teams (smaller team_rows),
                      "vertical" prefers taller teams (smaller team_cols).
        """
        total = columns * num_rows

        # Check if total handouts can be evenly divided
        if total % handouts_per_team != 0:
            return None, None

        num_teams = total // handouts_per_team
        if num_teams < 1:
            return None, None  # Invalid configuration

        # Find all valid team rectangle sizes (team_cols × team_rows = handouts_per_team)
        valid_layouts = []
        for team_rows in range(1, handouts_per_team + 1):
            if handouts_per_team % team_rows == 0:
                team_cols = handouts_per_team // team_rows
                if columns % team_cols == 0 and num_rows % team_rows == 0:
                    valid_layouts.append((team_cols, team_rows))

        if not valid_layouts:
            return None, None

        # Sort based on grouping preference
        if grouping == "vertical":
            # Prefer vertical grouping (smaller team_cols = taller teams)
            valid_layouts.sort(key=lambda x: x[0])
        else:
            # Prefer horizontal grouping (smaller team_rows = wider teams)
            valid_layouts.sort(key=lambda x: x[1])

        return valid_layouts[0]

    def build_cell_body(self, block):
        """Build the Typst content placed in every cell of a block: an optional
        image, an optional (possibly multi-line) text, and a centred caption
        beneath the image when both are present."""
        fs = block.get("font_size") or self.args.font_size

        def wrap_text(s):
            if block.get("font_family"):
                return f'text(font: "{block["font_family"]}", size: {fs}pt)[{s}]'
            return f"text(size: {fs}pt)[{s}]"

        img_expr = None
        if block.get("image"):
            image_path = block["image"]
            if block.get("rotate"):
                image_path = rotate_image(
                    self.resolve_image_path(image_path), block["rotate"]
                )
                self._temp_files.append(image_path)
            image_path = self.prepare_image(image_path)
            img_qwidth = block.get("resize_image") or 1.0
            imgwidth = IMGWIDTH.replace("<QWIDTH>", f"{img_qwidth * 100}%")
            img_expr = IMG.replace("<IMGPATH>", tex_image_path(image_path)).replace(
                "<IMGWIDTH>", imgwidth
            )

        text_expr = wrap_text(block["text"]) if block.get("text") else None

        if img_expr and text_expr:
            return (
                f"stack(dir: ttb, spacing: 1mm, {img_expr}, "
                f"align(center, {text_expr}))"
            )
        if img_expr:
            return img_expr
        return text_expr or wrap_text("")

    def generate_regular_block(self, block_):
        block = block_.copy()
        if not (block.get("image") or block.get("text")):
            return
        columns = block["columns"]
        num_rows = block.get("rows") or 1
        handouts_per_team = block.get("handouts_per_team") or 3
        grouping = block.get("grouping") or "horizontal"

        # How the sheet is cut into teams: each team is a solid-bordered
        # team_cols x team_rows rectangle. If it does not divide evenly, treat
        # the whole block as one team (solid outline, all-dashed inside).
        team_cols, team_rows = self.get_cut_direction(
            columns, num_rows, handouts_per_team, grouping
        )
        teamed = bool(team_cols and team_rows)
        if not teamed:
            team_cols, team_rows = columns, num_rows
        if self.args.debug:
            print(
                f"team_cols: {team_cols}, team_rows: {team_rows}, grouping: {grouping}"
            )

        # Gaps sit between teams only (cells are flush within a team), so the row
        # width is divided among `columns` cells plus the between-team gaps.
        gap = block.get("hspace") or self.SPACE
        n_team_cols = columns // team_cols
        available_width = self.get_page_width() * self.get_block_max_width(block)
        cellw = self.args.boxwidth or round(
            (available_width - (n_team_cols - 1) * gap) / columns, 3
        )
        if self.args.debug:
            print(f"columns: {columns}, cellw: {cellw}, gap: {gap}")

        pad = self.effective_tikz_mm(block)
        fs = block.get("font_size") or self.args.font_size
        strut = round(fs * self.STRUT_EM * 25.4 / 72, 3)  # em -> mm
        cellbody = self.build_cell_body(block)
        centered = "false" if block.get("no_center") else "true"
        return (
            f"#handout({columns}, {num_rows}, {team_cols}, {team_rows}, "
            f"{gap}mm, {cellw}mm, {pad}mm, {strut}mm, "
            f"{str(teamed).lower()}, {centered}, {cellbody})"
        )


    def generate(self):
        for block in self.parse_input(self.args.filename):
            if not block:
                self.blocks.append("\n#pagebreak()\n")
                continue
            if self.args.debug:
                print(block)
            label = None
            grid = None
            if block.get("for_question"):
                label = self.generate_for_question(block["for_question"])
            if block.get("columns"):
                grid = self.generate_regular_block(block)
            if label or grid:
                self.blocks.append(self.wrap_question_block(label, grid))
        return "\n\n".join(self.blocks)


def get_num_teams(filepath):
    """Extract the number of teams from the first regular block of a .hndt file."""
    contents = read_file(filepath)
    blocks = parse_handouts(contents)
    for block in blocks:
        if block.get("columns"):
            columns = block["columns"]
            num_rows = block.get("rows") or 1
            handouts_per_team = block.get("handouts_per_team") or 3
            total = columns * num_rows
            if total % handouts_per_team == 0:
                return total // handouts_per_team
    return None


def typst_root():
    """Root passed to ``typst compile`` so absolute image paths (including
    optimized temp files outside the project dir) remain readable."""
    return os.path.abspath(os.sep)


def typst_compile_command(typst_path, typ_basename, pdf_basename):
    """Build the ``typst compile`` argv, pointing the font search at the
    bundled fonts (Noto Sans) while still allowing system fonts."""
    return [
        typst_path,
        "compile",
        "--root",
        typst_root(),
        "--font-path",
        get_bundled_fonts_dir(),
        typ_basename,
        pdf_basename,
    ]


def typst_query_command(typst_path, typ_basename, label):
    """Build the ``typst query`` argv used to measure a handout: typst paginates
    the document itself and we read back a single ``<label>`` metadata element
    (its ``value`` field as JSON) instead of rendering and parsing a PDF."""
    return [
        typst_path,
        "query",
        "--root",
        typst_root(),
        "--font-path",
        get_bundled_fonts_dir(),
        typ_basename,
        f"<{label}>",
        "--field",
        "value",
        "--one",
    ]


def ensure_typst_path(args):
    typst_path = get_typst_path()
    if not typst_path:
        print("typst is not present, installing it...")
        install_typst(args)
        typst_path = get_typst_path()
    if not typst_path:
        raise ChgksuiteError("typst couldn't be installed successfully :(")
    return typst_path


def process_file(args, file_dir, bn):
    generator = HandoutGenerator(args)
    typst_contents = generator.generate()
    add_n_teams = getattr(args, "add_n_teams", "off") == "on"
    num_teams = get_num_teams(args.filename) if add_n_teams else None
    if num_teams is not None:
        pdf_bn = f"{bn}_{num_teams}teams_{args.language}"
    else:
        pdf_bn = f"{bn}_{args.language}"
    typ_path = os.path.join(file_dir, f"{pdf_bn}.typ")
    write_file(typ_path, typst_contents)

    typst_path = ensure_typst_path(args)
    if args.debug:
        print(f"typst found at `{typst_path}`")

    output_file = replace_ext(typ_path, "pdf")
    proc = subprocess.run(
        typst_compile_command(
            typst_path, os.path.basename(typ_path), os.path.basename(output_file)
        ),
        check=False,
        cwd=file_dir,
        text=True,
        capture_output=True,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    proc.check_returncode()

    for tmp in generator._temp_files:
        try:
            os.remove(tmp)
        except OSError:
            pass

    if args.compress_pdf == "on":
        compress_pdf(output_file)

    print(f"Output file: {output_file}")

    if not args.debug:
        os.remove(typ_path)


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, args, file_dir, bn):
        self.args = args
        self.file_dir = file_dir
        self.bn = bn
        self.last_processed = 0

    def on_modified(self, event):
        if event.src_path == os.path.abspath(self.args.filename):
            # Debounce to avoid processing the same change multiple times
            current_time = time.time()
            if current_time - self.last_processed > 1:
                print(f"File {self.args.filename} changed, regenerating PDF...")
                process_file(self.args, self.file_dir, self.bn)
                self.last_processed = current_time


def run_handouter(args):
    file_dir = os.path.dirname(os.path.abspath(args.filename))
    bn, _ = os.path.splitext(os.path.basename(args.filename))

    process_file(args, file_dir, bn)

    if args.watch:
        print(f"Watching {args.filename} for changes. Press Ctrl+C to stop.")
        event_handler = FileChangeHandler(args, file_dir, bn)
        observer = Observer()
        observer.schedule(event_handler, path=file_dir, recursive=False)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()


def gui_handouter(args):
    if hasattr(args, "filename") and args.filename:
        set_lastdir(os.path.dirname(os.path.abspath(args.filename)))
    if args.handoutssubcommand in ("4s2hndt", "generate"):
        generate_handouts(args)
    elif args.handoutssubcommand in ("hndt2pdf", "run"):
        run_handouter(args)
    elif args.handoutssubcommand == "install":
        install_typst(args)
    elif args.handoutssubcommand == "split_fit":
        from chgksuite.handouter.split_fit import run_split_fit

        exit_code = run_split_fit(args)
        if exit_code:
            raise SystemExit(exit_code)
    elif args.handoutssubcommand == "pack":
        pack_handouts(args)
    elif args.handoutssubcommand == "create_html":
        from chgksuite.handouter.html_handout import create_html

        create_html(args)
    elif args.handoutssubcommand == "html2img":
        from chgksuite.handouter.html_handout import html2img

        html2img(args)
