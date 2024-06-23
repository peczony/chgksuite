#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import os
import shutil
import sys
import toml
import re

from chgksuite.composer.chgksuite_parser import parse_4s
from chgksuite.composer.composer_common import _parse_4s_elem, parseimg
from chgksuite.common import get_source_dirs


def read_file(filepath):
    with open(filepath, encoding="utf8") as f:
        cnt = f.read()
    return cnt


def write_file(filepath, cnt):
    with open(filepath, "w", encoding="utf8") as f:
        f.write(cnt)
    

def straighten(lst_):
    for element in lst_:
        if isinstance(element, list):
            for el2 in straighten(element):
                yield el2
        else:
            yield element


def get_images_from_element(element):
    if isinstance(element, list):
        element = straighten(element)
    else:
        element = [element]
    images = []
    for _el in element:
        parsed = _parse_4s_elem(_el)
        for tup in parsed:
            if tup[0] == "img":
                try:
                    parsed_img = parseimg(tup[1])
                    images.append(parsed_img["imgfile"])
                except Exception as e:
                    print(f"couldn't parse img {tup[1]}: {type(e)} {e}", file=sys.stderr)
    return images


def get_handout_text(re_, labels, text, number):
    if isinstance(text, list):
        text = "\n".join(straighten(text))
    srch = re_.search(text)
    if srch:
        return srch.group("handout_text")
    elif labels["question_labels"]["handout_short"] in text:
        print(f"possibly ill-marked handout at question {number} ({text[:100]})")
        return text
    

def add_hndt(number, text, file_path, handout_type="text"):
    assert handout_type in ("text", "image")
    result = [
        f"for_question: {number}",
        "columns: 3",
        "rows: 3"
    ]
    if handout_type == "image":
        result.append(f"image: {text}")
    else:
        result.append("")
        result.append(text)
    write_file(file_path, "\n".join(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    parser.add_argument("--folder", default="release")
    parser.add_argument("--lang", default="ru")
    parser.add_argument("--add_hndt", action="store_true")
    args = parser.parse_args()

    cnt = read_file(args.filename)
    parsed = parse_4s(cnt)

    if os.path.isdir(args.folder):
        print(f"folder already exists: {args.folder}")
        sys.exit(1)

    if not os.path.isdir(args.folder):
        os.mkdir(args.folder)
    if args.add_hndt:
        hndt_folder = os.path.join(args.folder, "hndt")
        os.mkdir(hndt_folder)

    replacements = []

    _, resourcedir = get_source_dirs()
    labels = toml.loads(
        read_file(os.path.join(resourcedir, f"labels_{args.lang}.toml"))
    )
    handout_re = re.compile(
        "\\["
        + labels["question_labels"]["handout_short"]
        + ".+?:( |\n)(?P<handout_text>.+?)\\]",
        flags=re.DOTALL,
    )

    for tup in parsed:
        if tup[0] == "Question":
            question = tup[1]
            number = question["number"]
            question_prefix = f"q{str(number).zfill(2)}"
            question_images = get_images_from_element(question["question"])

            if not question_images and args.add_hndt:
                handout_text = get_handout_text(handout_re, labels, question["question"], number)
                if handout_text:
                    add_hndt(number, handout_text, os.path.join(hndt_folder, question_prefix + ".txt"), handout_type="text")

            for i, imgfile in enumerate(question_images):
                _, ext = os.path.splitext(imgfile)
                suffix = f"_{i}" if i else ""
                new_prefix = f"q{str(number).zfill(2)}" + suffix
                new_name = new_prefix + ext
                shutil.copy(imgfile, os.path.join(args.folder, new_name))
                replacements.append((imgfile, new_name))
                if args.add_hndt:
                    add_hndt(
                        number,
                        imgfile,
                        os.path.join(hndt_folder, new_prefix + ".txt"),
                        handout_type="image",
                    )
                    shutil.copy(imgfile, os.path.join(hndt_folder, imgfile))
            answer_images = []
            for field in ("answer", "comment"):
                answer_images.extend(get_images_from_element(question[field]))
            for i, imgfile in enumerate(answer_images):
                _, ext = os.path.splitext(imgfile)
                suffix = f"_{i}" if i else ""
                new_prefix = f"q{str(number).zfill(2)}_answer" + suffix
                new_name = new_prefix + ext
                shutil.copy(imgfile, os.path.join(args.folder, new_name))
                replacements.append((imgfile, new_name))
                if args.add_hndt:
                    add_hndt(
                        number,
                        imgfile,
                        os.path.join(hndt_folder, new_prefix + ".txt"),
                        handout_type="image",
                    )
                    shutil.copy(imgfile, os.path.join(hndt_folder, imgfile))

    for from_, to_ in replacements:
        cnt = cnt.replace(from_, to_)
    write_file(os.path.join(args.folder, os.path.basename(args.filename)), cnt)


if __name__ == "__main__":
    main()
