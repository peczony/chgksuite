#!usr/bin/env python
# -*- coding: utf-8 -*-
import codecs
import json
import os
import shutil
import sys

from chgksuite.common import (
    DefaultArgs,
    get_chgksuite_dir,
    get_lastdir,
    get_source_dirs,
    init_logger,
    log_wrap,
    set_lastdir,
)
from chgksuite.composer.chgksuite_parser import parse_4s
from chgksuite.composer.composer_common import make_filename, make_temp_directory
from chgksuite.composer.db import DbExporter
from chgksuite.composer.docx import DocxExporter
from chgksuite.composer.latex import LatexExporter
from chgksuite.composer.lj import LjExporter
from chgksuite.composer.pptx import PptxExporter
from chgksuite.composer.reddit import RedditExporter
from chgksuite.composer.stats import StatsAdder
from chgksuite.composer.telegram import TelegramExporter


def gui_compose(args, logger=None):
    sourcedir = get_source_dirs()[0]

    argsdict = vars(args)
    logger = logger or init_logger("composer", debug=args.debug)
    logger.debug(log_wrap(argsdict))

    ld = get_lastdir()
    if args.filename:
        if isinstance(args.filename, list):
            ld = os.path.dirname(os.path.abspath(args.filename[0]))
        else:
            ld = os.path.dirname(os.path.abspath(args.filename))
    set_lastdir(ld)
    if not args.filename:
        print("No file specified.")
        sys.exit(1)

    if isinstance(args.filename, list):
        if not args.merge:
            for fn in args.filename:
                targetdir = os.path.dirname(os.path.abspath(fn))
                filename = os.path.basename(os.path.abspath(fn))
                process_file_wrapper(filename, sourcedir, targetdir, args)
        else:
            targetdir = os.path.dirname(os.path.abspath(args.filename[0]))
            process_file_wrapper(args.filename, sourcedir, targetdir, args)
    else:
        targetdir = os.path.dirname(os.path.abspath(args.filename))
        filename = os.path.basename(os.path.abspath(args.filename))
        process_file_wrapper(filename, sourcedir, targetdir, args)


def process_file_wrapper(filename, sourcedir, targetdir, args):
    resourcedir = os.path.join(sourcedir, "resources")
    with make_temp_directory(dir=get_chgksuite_dir()) as tmp_dir:
        for fn in [
            args.docx_template,
            os.path.join(resourcedir, "fix-unnumbered-sections.sty"),
            args.tex_header,
        ]:
            shutil.copy(fn, tmp_dir)
        process_file(filename, tmp_dir, targetdir, args)


def parse_filepath(filepath, args=None):
    args = args or DefaultArgs()
    with codecs.open(filepath, "r", "utf8") as input_file:
        input_text = input_file.read()
    input_text = input_text.replace("\r", "")
    return parse_4s(input_text, randomize=args.randomize, debug=args.debug)


def make_merged_filename(filelist):
    filelist = [os.path.splitext(os.path.basename(x))[0] for x in filelist]
    prefix = os.path.commonprefix(filelist)
    suffix = "_".join(x[len(prefix) :] for x in filelist)
    return prefix + suffix


def process_file(filename, tmp_dir, targetdir, args=None, logger=None):
    dir_kwargs = dict(tmp_dir=tmp_dir, targetdir=targetdir)
    logger = logger or init_logger("composer")

    if isinstance(filename, list):
        structure = []
        for x in filename:
            structure.extend(parse_filepath(os.path.join(targetdir, x), args=args))
        filename = make_merged_filename(filename)
    else:
        structure = parse_filepath(os.path.join(targetdir, filename), args=args)

    if args.debug:
        debug_fn = os.path.join(
            targetdir,
            make_filename(os.path.basename(filename), "dbg", args),
        )
        with codecs.open(debug_fn, "w", "utf8") as output_file:
            output_file.write(json.dumps(structure, indent=2, ensure_ascii=False))

    if not args.filetype:
        print("Filetype not specified.")
        sys.exit(1)
    if args.filetype == "docx":
        spoilers = args.spoilers
    else:
        spoilers = "off" if args.nospoilers else "on"
    logger.info("Exporting to {}, spoilers are {}...\n".format(args.filetype, spoilers))

    if args.filetype == "docx":
        if args.screen_mode == "off":
            addsuffix = ""
        elif args.screen_mode == "replace_all":
            addsuffix = "_screen"
        elif args.screen_mode == "add_versions":
            addsuffix = "_screen_versions"
        if args.spoilers != "off":
            addsuffix += "_spoilers"
        outfilename = os.path.join(
            targetdir, make_filename(filename, "docx", args, addsuffix=addsuffix)
        )
        exporter = DocxExporter(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "tex":
        outfilename = os.path.join(tmp_dir, make_filename(filename, "tex", args))
        exporter = LatexExporter(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "lj":
        exporter = LjExporter(structure, args, dir_kwargs)
        exporter.export()

    if args.filetype == "base":
        exporter = DbExporter(structure, args, dir_kwargs)
        outfilename = os.path.join(targetdir, make_filename(filename, "txt", args))
        exporter.export(outfilename)

    if args.filetype == "redditmd":
        exporter = RedditExporter(structure, args, dir_kwargs)
        outfilename = os.path.join(targetdir, make_filename(filename, "md", args))
        exporter.export(outfilename)

    if args.filetype == "pptx":
        outfilename = os.path.join(targetdir, make_filename(filename, "pptx", args))
        exporter = PptxExporter(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "add_stats":
        outfilename = os.path.join(
            targetdir,
            make_filename(filename, "4s", args, addsuffix="_with_stats"),
        )
        exporter = StatsAdder(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "telegram":
        exporter = TelegramExporter(structure, args, dir_kwargs)
        exporter.export()


def main():
    print("This program was not designed to run standalone.")


if __name__ == "__main__":
    main()
