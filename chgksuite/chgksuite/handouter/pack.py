import logging
import math
import os
import subprocess

from pypdf import PdfWriter

from chgksuite.handouter.utils import compress_pdf, parse_handouts

logger = logging.getLogger(__name__)


def only_handout_or_skip(filename, parsed):
    handouts = [handout for handout in parsed if handout]
    if not handouts:
        print(f"skipping {filename}: no handouts found")
        return None
    if len(handouts) > 1:
        print(
            f"skipping {filename}: contains {len(handouts)} handouts; "
            "pack only uses split-fitted single-handout files"
        )
        return None
    return handouts[0]


def run_hndt(fullpath, args):
    spargs = ["chgksuite", "handouts", "hndt2pdf"]
    if args.font:
        spargs.extend(["--font", args.font])
    spargs.append(fullpath)
    proc = subprocess.run(spargs, cwd=args.folder, check=True, capture_output=True)
    lines = [line for line in proc.stdout.decode("utf8").split("\n") if line]
    return lines[-1].split("Output file:")[1].strip()


def pdf_output(pages, filename, compress=True):
    print(f"merging to {filename}, total pages {len(pages)}...")
    merger = PdfWriter()

    for pdf in pages:
        merger.append(pdf)

    merger.write(filename)
    merger.close()
    if compress:
        compress_pdf(filename)


def pack_handouts(args):
    if not args.folder:
        args.folder = os.getcwd()
    args.folder = os.path.abspath(args.folder)

    color_pages = []
    bw_pages = []

    for fn in sorted(os.listdir(args.folder)):
        if not fn.endswith((".hndt", ".txt")):
            continue
        fullpath = os.path.join(args.folder, fn)
        with open(fullpath, encoding="utf8") as f:
            contents = f.read()
        try:
            parsed = parse_handouts(contents)
        except Exception:
            logger.exception(f"couldn't parse {fn}, skipping")
            continue
        handout = only_handout_or_skip(fn, parsed)
        if handout is None:
            continue
        color = handout.get("color") or 0
        handouts_per_team = handout.get("handouts_per_team") or 3
        total_handouts_per_page = handout["columns"] * handout["rows"]
        teams_per_page = total_handouts_per_page / handouts_per_team
        pages = math.ceil((args.n_teams + 1) / teams_per_page)
        print(f"processing {fn}")
        print(f"color = {color}")
        print(f"handouts_per_team = {handouts_per_team}")
        print(f"total_handouts_per_page = {total_handouts_per_page}")
        print(f"teams_per_page = {round(teams_per_page, 1)}")
        print(f"pages = {pages}")
        print("running hndt...")
        output_file = run_hndt(fullpath, args)
        if color:
            color_pages += [output_file] * pages
        else:
            bw_pages += [output_file] * pages
    compress = args.compress_pdf == "on"
    if color_pages:
        pdf_output(
            color_pages,
            os.path.join(args.folder, args.output_filename_prefix + "_color.pdf"),
            compress=compress,
        )
    if bw_pages:
        pdf_output(
            bw_pages,
            os.path.join(args.folder, args.output_filename_prefix + "_bw.pdf"),
            compress=compress,
        )
