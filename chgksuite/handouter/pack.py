#!/usr/bin/env python
# -*- coding: utf-8 -*-
import math
import os
import subprocess

from pypdf import PdfWriter

from chgksuite.handouter.utils import parse_handouts


def run_hndt(fullpath, args):
    spargs = ["hndt"]
    if args.font:
        spargs.extend(["--font", args.font])
    spargs.append(fullpath)
    proc = subprocess.run(spargs, cwd=args.folder, check=True, capture_output=True)
    ns = globals()
    ns.update(locals())
    lines = [line for line in proc.stdout.decode("utf8").split("\n") if line]
    return lines[-1].split("Output file:")[1].strip()


def pdf_output(pages, filename):
    print(f"merging to {filename}, total pages {len(pages)}...")
    merger = PdfWriter()

    for pdf in pages:
        merger.append(pdf)

    merger.write(filename)
    merger.close()


def pack_handouts(args):
    if not args.folder:
        args.folder = os.getcwd()
    args.folder = os.path.abspath(args.folder)

    color_pages = []
    bw_pages = []

    for fn in sorted(os.listdir(args.folder)):
        if not fn.endswith(".txt"):
            continue
        fullpath = os.path.join(args.folder, fn)
        with open(fullpath, encoding="utf8") as f:
            contents = f.read()
        parsed = parse_handouts(contents)
        if len(parsed) > 1:
            print(f"skipping {fn}: more than one handout per txt is not supported")
            continue
        color = parsed[0].get("color") or 0
        handouts_per_team = parsed[0].get("handouts_per_team") or 3
        total_handouts_per_page = parsed[0]["columns"] * parsed[0]["rows"]
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
    if color_pages:
        pdf_output(
            color_pages,
            os.path.join(args.folder, args.output_filename_prefix + "_color.pdf"),
        )
    if bw_pages:
        pdf_output(
            bw_pages,
            os.path.join(args.folder, args.output_filename_prefix + "_bw.pdf"),
        )
