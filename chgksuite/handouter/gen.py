#!/usr/bin/env python
# -*- coding: utf-8 -*-
import itertools
import os
import re
from collections import defaultdict

import toml

from chgksuite.common import get_source_dirs
from chgksuite.composer.chgksuite_parser import parse_4s
from chgksuite.composer.composer_common import _parse_4s_elem, parseimg
from chgksuite.handouter.utils import read_file, write_file


def postprocess(s):
    return s.replace("\\_", "_")


def generate_handouts_list(handouts, output_dir, base_name, parsed):
    """Generate a human-readable file with question numbers that have handouts."""
    question_numbers = sorted([int(h["for_question"]) for h in handouts])

    content = "ВОПРОСЫ С РАЗДАТОЧНЫМ МАТЕРИАЛОМ:\n\n"
    content += f"Сквозная нумерация:\n{', '.join(map(str, question_numbers))}\n\n"

    content += "По турам:\n"
    tour = 0
    by_tour = {}
    for tup in parsed:
        if tup[0] == "section":
            tour += 1
            by_tour[tour] = []
        if tup[0] == "Question":
            if tour == 0:
                tour = 1
                by_tour[tour] = []
            if tup[1]["number"] in question_numbers:
                by_tour[tour].append(tup[1]["number"])

    for tour in sorted(by_tour):
        tour_handouts = by_tour[tour]
        if tour_handouts:
            content += f"Тур {tour}: {', '.join(map(str, tour_handouts))}\n"
        else:
            content += f"Тур {tour}: нет раздаток\n"

    output_fn = os.path.join(output_dir, base_name + "_handouts_list.txt")
    write_file(output_fn, content)
    print(f"File with list of handouts: {output_fn}")
    print(content)


def generate_handouts(args):
    _, resourcedir = get_source_dirs()
    labels = toml.loads(
        read_file(os.path.join(resourcedir, f"labels_{args.lang}.toml"))
    )
    handout_re_text = (
        "\\["
        + labels["question_labels"]["handout_short"]
        + ".+?:( |\n)(?P<handout_text>.+?)\\]"
    )
    handout_re = re.compile(
        handout_re_text,
        flags=re.DOTALL,
    )

    cnt = read_file(args.filename)
    parsed = parse_4s(cnt)

    questions = [q[1] for q in parsed if q[0] == "Question"]
    handouts = []
    for q in questions:
        if isinstance(q["question"], list):
            question_text = "\n".join(itertools.chain.from_iterable(q["question"]))
        else:
            question_text = q["question"]
        question_text_lower = question_text.lower()
        srch = handout_re.search(question_text)
        if srch:
            text = postprocess(srch.group("handout_text"))
            elems = _parse_4s_elem(text)
            img = [el for el in elems if el[0] == "img"]
            if img:
                try:
                    parsed_img = parseimg(img[0][1])
                except Exception as e:
                    print(
                        f"Image file for question {q['number']} not found, add it by hand (exception {type(e)} {e})"
                    )
                    continue
            else:
                parsed_img = None
            res = {"for_question": q["number"]}
            if parsed_img:
                res["image"] = parsed_img["imgfile"]
            else:
                res["text"] = text
            handouts.append(res)
        elif (
            "раздат" in question_text_lower
            or "роздан" in question_text_lower
            or "(img" in question_text_lower
        ):
            print(f"probably badly formatted handout for question {q['number']}")
            res = {"for_question": q["number"], "text": postprocess(question_text)}
            handouts.append(res)
    result = []
    result_by_question = defaultdict(list)
    for handout in handouts:
        if "image" in handout:
            key = "image"
            prefix = "image: "
        else:
            key = "text"
            prefix = ""
        value = handout[key]
        formatted = (
            f"for_question: {handout['for_question']}\n" if not args.separate else ""
        ) + f"columns: 3\n\n{prefix}{value}"
        result.append(formatted)
        result_by_question[handout["for_question"]].append(formatted)
    output_dir = os.path.dirname(os.path.abspath(args.filename))
    bn, _ = os.path.splitext(os.path.basename(args.filename))

    if args.separate:
        for k, v in result_by_question.items():
            if len(v) > 1:
                for i, cnt in enumerate(v):
                    output_fn = os.path.join(
                        output_dir, f"{bn}_q{k.zfill(2)}_{i + 1}.txt"
                    )
                    print(output_fn)
                    write_file(output_fn, cnt)
            else:
                output_fn = os.path.join(output_dir, f"{bn}_q{str(k).zfill(2)}.txt")
                print(output_fn)
                write_file(output_fn, v[0])
    else:
        output_fn = os.path.join(output_dir, bn + "_handouts.txt")
        print(f"output filename: {output_fn}")
        write_file(output_fn, "\n---\n".join(result))

    if args.list_handouts:
        generate_handouts_list(handouts, output_dir, bn, parsed)
