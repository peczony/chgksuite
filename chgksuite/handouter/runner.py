#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from chgksuite.handouter.gen import generate_handouts
from chgksuite.handouter.pack import pack_handouts
from chgksuite.handouter.installer import get_tectonic_path, install_tectonic
from chgksuite.handouter.tex_internals import (
    GREYTEXT,
    GREYTEXT_LANGS,
    HEADER,
    IMG,
    IMGWIDTH,
    TIKZBOX_END,
    TIKZBOX_INNER,
    TIKZBOX_START,
)
from chgksuite.handouter.utils import parse_handouts, read_file, replace_ext, write_file


class HandoutGenerator:
    SPACE = 1.5  # mm

    def __init__(self, args):
        self.args = args
        self.blocks = [self.get_header()]

    def get_header(self):
        header = HEADER
        header = (
            header.replace("<PAPERWIDTH>", str(self.args.paperwidth))
            .replace("<PAPERHEIGHT>", str(self.args.paperheight))
            .replace("<MARGIN_LEFT>", str(self.args.margin_left))
            .replace("<MARGIN_RIGHT>", str(self.args.margin_right))
            .replace("<MARGIN_TOP>", str(self.args.margin_top))
            .replace("<MARGIN_BOTTOM>", str(self.args.margin_bottom))
            .replace("<TIKZ_MM>", str(self.args.tikz_mm))
        )
        if self.args.font:
            header = header.replace("Arial", self.args.font)
        return header

    def parse_input(self, filepath):
        contents = read_file(filepath)
        return parse_handouts(contents)

    def generate_for_question(self, question_num):
        return GREYTEXT.replace(
            "<GREYTEXT>", GREYTEXT_LANGS[self.args.lang].format(question_num)
        )

    def make_tikzbox(self, block):
        if block.get("no_center"):
            align = ""
        else:
            align = ", align=center"
        textwidth = ", text width=\\boxwidthinner"
        fs = block.get("font_size") or self.args.font_size
        fontsize = "\\fontsize{FSpt}{LHpt}\\selectfont ".replace("FS", str(fs)).replace(
            "LH", str(round(fs * 1.2, 1))
        )
        contents = block["contents"]
        if block.get("font_family"):
            contents = "\\fontspec{" + block["font_family"] + "}" + contents
        return (
            TIKZBOX_INNER.replace("<CONTENTS>", contents)
            .replace("<ALIGN>", align)
            .replace("<TEXTWIDTH>", textwidth)
            .replace("<FONTSIZE>", fontsize)
        )

    def get_page_width(self):
        return self.args.paperwidth - self.args.margin_left - self.args.margin_right - 2

    def generate_regular_block(self, block_):
        block = block_.copy()
        if not (block.get("image") or block.get("text")):
            return
        columns = block["columns"]
        spaces = block["columns"] - 1
        boxwidth = self.args.boxwidth or round(
            (self.get_page_width() - spaces * self.SPACE) / block["columns"],
            3,
        )
        total_width = boxwidth * columns + spaces * self.SPACE
        if self.args.debug:
            print(
                f"columns: {columns}, boxwidth: {boxwidth}, total width: {total_width}"
            )
        boxwidthinner = self.args.boxwidthinner or (boxwidth - 2 * self.args.tikz_mm)
        header = [
            r"\setlength{\boxwidth}{<Q>mm}%".replace("<Q>", str(boxwidth)),
            r"\setlength{\boxwidthinner}{<Q>mm}%".replace("<Q>", str(boxwidthinner)),
        ]
        rows = []
        contents = []
        if block.get("image"):
            img_qwidth = block.get("resize_image") or 1.0
            imgwidth = IMGWIDTH.replace("<QWIDTH>", str(img_qwidth))
            contents.append(
                IMG.replace("<IMGPATH>", block["image"]).replace("<IMGWIDTH>", imgwidth)
            )
        if block.get("text"):
            contents.append(block["text"])
        block["contents"] = "\\linebreak\n".join(contents)
        if block.get("no_center"):
            block["centering"] = ""
        else:
            block["centering"] = "\\centering"
        for _ in range(block.get("rows") or 1):
            row = (
                TIKZBOX_START.replace("<CENTERING>", block["centering"])
                + "\n".join([self.make_tikzbox(block)] * block["columns"])
                + TIKZBOX_END
            )
            rows.append(row)
        return "\n".join(header) + "\n" + "\n\n\\vspace{1mm}\n\n".join(rows)

    def generate(self):
        for block in self.parse_input(self.args.filename):
            if not block:
                self.blocks.append("\n\\clearpage\n")
                continue
            if self.args.debug:
                print(block)
            if block.get("for_question"):
                self.blocks.append(self.generate_for_question(block["for_question"]))
            if block.get("columns"):
                block = self.generate_regular_block(block)
                if block:
                    self.blocks.append(block)
        self.blocks.append("\\end{document}")
        return "\n\n".join(self.blocks)


def process_file(args, file_dir, bn):
    tex_contents = HandoutGenerator(args).generate()
    tex_path = os.path.join(file_dir, f"{bn}_{args.lang}.tex")
    write_file(tex_path, tex_contents)

    tectonic_path = get_tectonic_path()
    if not tectonic_path:
        print("tectonic is not present, installing it...")
        install_tectonic(args)
        tectonic_path = get_tectonic_path()
    if not tectonic_path:
        raise Exception("tectonic couldn't be installed successfully :(")
    if args.debug:
        print(f"tectonic found at `{tectonic_path}`")

    subprocess.run(
        [tectonic_path, os.path.basename(tex_path)], check=True, cwd=file_dir
    )

    output_file = replace_ext(tex_path, "pdf")

    if args.compress:
        print(f"compressing {output_file}")
        size_before = round(os.stat(output_file).st_size / 1024)
        output_file_compressed = output_file[:-4] + ".compressed.pdf"
        subprocess.run(
            [
                "gs",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.5",
                f"-dPDFSETTINGS=/{args.pdfsettings}",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                f"-sOutputFile={output_file_compressed}",
                output_file,
            ],
            check=True,
        )
        shutil.move(output_file_compressed, output_file)
        size_after = round(os.stat(output_file).st_size / 1024)
        q = round(size_after / size_before, 1)
        print(f"before: {size_before}kb, after: {size_after}kb, compression: {q}")

    print(f"Output file: {output_file}")

    if not args.debug:
        os.remove(tex_path)


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
    if args.handoutssubcommand == "run":
        run_handouter(args)
    elif args.handoutssubcommand == "generate":
        generate_handouts(args)
    elif args.handoutssubcommand == "pack":
        pack_handouts(args)
    elif args.handoutssubcommand == "install":
        install_tectonic(args)
