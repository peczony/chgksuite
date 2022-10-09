#!/usr/bin/env python
# -*- coding: utf-8 -*-
import pprint
import re
import os
import pdb
import sys
import codecs
import json
import subprocess
import shlex
import logging
import base64
import itertools
import tempfile
import shutil
import chardet
import mammoth
import pypandoc
import dashtable
import bs4
from bs4 import BeautifulSoup
from parse import parse
import html2text

import chgksuite.typotools as typotools
from chgksuite.typotools import remove_excessive_whitespace as rew
from chgksuite.parser_db import chgk_parse_db
from chgksuite.common import (
    get_lastdir,
    set_lastdir,
    DummyLogger,
    log_wrap,
    DefaultNamespace,
    check_question,
    QUESTION_LABELS,
    get_source_dirs,
    compose_4s
)
from chgksuite.composer import gui_compose

debug = False
console_mode = False

ENC = sys.stdout.encoding or "utf8"
CONSOLE_ENC = sys.stdout.encoding or "utf8"
SEP = os.linesep
EDITORS = {
    "win32": "notepad",
    "linux2": "xdg-open",  # python2
    "linux": "xdg-open",  # python3
    "darwin": "open -t",
}
TEXTEDITOR = EDITORS[sys.platform]
regexes = {}


logger = DummyLogger()


def make_filename(s):
    return os.path.splitext(s)[0] + ".4s"


def debug_print(s):
    if debug is True:
        sys.stderr.write(s + SEP)


def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0] + indices, indices + [None])]


def load_regexes(regexfile):
    with codecs.open(regexfile, "r", "utf8") as f:
        regexes = json.loads(f.read())
    return {k: re.compile(v) for k, v in regexes.items()}


def chgk_parse(text, defaultauthor=None, regexes=None):
    """
    Parsing rationale: every Question has two required fields: 'question' and
    the immediately following 'answer'. All the rest are optional, as is
    the order of these fields. On the other hand, everything
    except the 'question' is obligatorily marked, while the 'question' is
    optionally marked. But IF the question is not marked, 'meta' comments
    between Questions will not be parsed as 'meta' but will be merged to
    'question's.
    Parsing is done by regexes in the following steps:

    1. Identify all the fields you can, mark them with their respective
        labels, mark all the others with ''
    2. Merge fields inside Question with '' lines between them
    3. Ensure every 'answer' has a 'question'
    4. Mark all remaining '' fields as 'meta'
    5. Prettify input
    6. Pack Questions into dicts
    7. Return the resulting structure

    """

    BADNEXTFIELDS = set(["question", "answer"])

    # WHITESPACE = set([' ', ' ', '\n', '\r'])
    # PUNCTUATION = set([',', '.', ':', ';', '?', '!'])

    structure = []

    if not regexes:
        _, resourcedir = get_source_dirs()
        regexes_file = os.path.join(resourcedir, "regexes.json")
        regexes = load_regexes(regexes_file)
    elif isinstance(regexes, str):
        regexes = load_regexes(regexes)

    def merge_to_previous(index):
        target = index - 1
        if structure[target][1]:
            structure[target][1] = (
                structure[target][1] + SEP + structure.pop(index)[1]
            )
        else:
            structure[target][1] = structure.pop(index)[1]

    def merge_to_next(index):
        target = structure.pop(index)
        structure[index][1] = target[1] + SEP + structure[index][1]

    def find_next_fieldname(index):
        target = index + 1
        if target < len(structure):
            while target < len(structure) - 1 and structure[target][0] == "":
                target += 1
            return structure[target][0]

    def merge_y_to_x(x, y):
        i = 0
        while i < len(structure):
            if structure[i][0] == x:
                while i + 1 < len(structure) and structure[i + 1][0] != y:
                    merge_to_previous(i + 1)
            i += 1

    def merge_to_x_until_nextfield(x):
        i = 0
        while i < len(structure):
            if structure[i][0] == x:
                while (
                    i + 1 < len(structure)
                    and structure[i + 1][0] == ""
                    and find_next_fieldname(i) not in BADNEXTFIELDS
                ):
                    merge_to_previous(i + 1)
            i += 1

    def dirty_merge_to_x_until_nextfield(x):
        i = 0
        while i < len(structure):
            if structure[i][0] == x:
                while i + 1 < len(structure) and structure[i + 1][0] == "":
                    merge_to_previous(i + 1)
            i += 1

    def apply_regexes(st):
        i = 0
        while i < len(st):
            matching_regexes = {
                (regex, regexes[regex].search(st[i][1]).start(0))
                for regex in set(regexes) - {"number", "date2"}
                if regexes[regex].search(st[i][1])
            }

            # If more than one regex matches string, split it and
            # insert into structure separately.

            if len(matching_regexes) == 1:
                st[i][0] = matching_regexes.pop()[0]
            elif len(matching_regexes) > 1:
                sorted_r = sorted(matching_regexes, key=lambda x: x[1])
                slices = []
                for j in range(1, len(sorted_r)):
                    slices.append(
                        [
                            sorted_r[j][0],
                            st[i][1][
                                sorted_r[j][1] : sorted_r[j + 1][1]
                                if j + 1 < len(sorted_r)
                                else len(st[i][1])
                            ],
                        ]
                    )
                for slice_ in slices:
                    st.insert(i + 1, slice_)
                st[i][0] = sorted_r[0][0]
                st[i][1] = st[i][1][: sorted_r[1][1]]
            i += 1

    if defaultauthor:
        logger.info(
            "The default author is {}. "
            "Missing authors will be substituted with them".format(
                log_wrap(defaultauthor)
            )
        )

    # 1.
    sep = "\r\n" if "\r\n" in text else "\n"

    fragments = [
        [["", rew(xx)] for xx in x.split(sep) if xx]
        for x in text.split(sep + sep)
    ]

    for fragment in fragments:
        apply_regexes(fragment)
        elements = {x[0] for x in fragment}
        if "answer" in elements and not fragment[0][0]:
            fragment[0][0] = "question"
    structure = list(itertools.chain(*fragments))
    i = 0

    if debug:
        with codecs.open("debug_1.json", "w", "utf8") as f:
            f.write(json.dumps(structure, ensure_ascii=False, indent=4))

    # hack for https://gitlab.com/peczony/chgksuite/-/issues/23; TODO: make less hacky
    for i, element in enumerate(structure):
        if (
            "дуплет." in element[1].lower().split() or "блиц." in element[1].lower().split()
            and element[0] != "question" and (i == 0 or structure[i - 1][0] != "question")
        ):
            element[0] = "question"

    if debug:
        with codecs.open("debug_1a.json", "w", "utf8") as f:
            f.write(json.dumps(structure, ensure_ascii=False, indent=4))

    # 2.

    merge_y_to_x("question", "answer")
    merge_to_x_until_nextfield("answer")
    merge_to_x_until_nextfield("comment")

    if debug:
        with codecs.open("debug_2.json", "w", "utf8") as f:
            f.write(json.dumps(structure, ensure_ascii=False, indent=4))

    # 3.

    i = 0
    while i < len(structure):
        if structure[i][0] == "answer" and structure[i - 1][0] not in (
            "question",
            "newquestion",
        ):
            structure.insert(i, ["newquestion", ""])
            i = 0
        i += 1

    i = 0
    while i < len(structure) - 1:
        if structure[i][0] == "" and structure[i + 1][0] == "newquestion":
            merge_to_next(i)
            if regexes["number"].search(rew(structure[i][1])) and not regexes[
                "number"
            ].search(rew(structure[i - 1][1])):
                structure[i][0] = "question"
                structure[i][1] = regexes["number"].sub(
                    "", rew(structure[i][1])
                )
                try:
                    structure.insert(
                        i,
                        [
                            "number",
                            int(
                                regexes["number"]
                                .search(rew(structure[i][1]))
                                .group(0)
                            ),
                        ],
                    )
                except:
                    pass
            i = 0
        i += 1

    for element in structure:
        if element[0] == "newquestion":
            element[0] = "question"

    dirty_merge_to_x_until_nextfield("source")

    for _id, element in enumerate(structure):
        if (
            element[0] == "author"
            and re.search(
                r"^{}$".format(regexes["author"].pattern), rew(element[1])
            )
            and _id + 1 < len(structure)
        ):
            merge_to_previous(_id + 1)

    merge_to_x_until_nextfield("zachet")
    merge_to_x_until_nextfield("nezachet")

    if debug:
        with codecs.open("debug_3.json", "w", "utf8") as f:
            f.write(json.dumps(structure, ensure_ascii=False, indent=4))

    # 4.

    structure = [x for x in structure if [x[0], rew(x[1])] != ["", ""]]

    if structure[0][0] == "" and regexes["number"].search(
        rew(structure[0][1])
    ):
        merge_to_next(0)

    for _id, element in enumerate(structure):
        if element[0] == "":
            element[0] = "meta"
        if element[0] in regexes and element[0] not in [
            "tour",
            "tourrev",
            "editor",
        ]:
            if element[0] == "question":
                try:
                    num = regexes["question"].search(element[1]).group(1)
                    structure.insert(_id, ["number", num])
                except:
                    pass
            # TODO: переделать корявую обработку авторки на нормальную
            before_replacement = element[1]
            element[1] = regexes[element[0]].sub("", element[1], 1)
            if element[1].startswith(SEP):
                element[1] = element[1][len(SEP) :]
            if element[0] == "author" and "авторка:" in before_replacement.lower():
                element[1] = "!!Авторка" + element[1]

    if debug:
        with codecs.open("debug_4.json", "w", "utf8") as f:
            f.write(json.dumps(structure, ensure_ascii=False, indent=4))

    # 5.

    for _id, element in enumerate(structure):

        # remove question numbers

        if element[0] == "question":
            try:
                num = regexes["question"].search(element[1]).group(1)
                structure.insert(_id, ["number", num])
            except:
                pass
            element[1] = regexes["question"].sub("", element[1])

        # detect inner lists

        mo = {
            m
            for m in re.finditer(
                r"(\s+|^)(\d+)[\.\)]\s*(?!\d)", element[1], re.U
            )
        }
        if len(mo) > 1:
            sorted_up = sorted(mo, key=lambda m: int(m.group(2)))
            j = 0
            list_candidate = []
            while j == int(sorted_up[j].group(2)) - 1:
                list_candidate.append(
                    (j + 1, sorted_up[j].group(0), sorted_up[j].start())
                )
                if j + 1 < len(sorted_up):
                    j += 1
                else:
                    break
            if len(list_candidate) > 1:
                if element[0] != "question" or (
                    element[0] == "question"
                    and "дуплет" in element[1].lower()
                    or "блиц" in element[1].lower()
                ):
                    part = partition(
                        element[1], [x[2] for x in list_candidate]
                    )
                    lc = 0
                    while lc < len(list_candidate):
                        part[lc + 1] = part[lc + 1].replace(
                            list_candidate[lc][1], "", 1
                        )
                        lc += 1
                    element[1] = (
                        [part[0], part[1:]] if part[0] != "" else part[1:]
                    )

        # turn source into list if necessary
        def _replace_once(regex, val, to_replace):
            srch = regex.search(val)
            if srch:
                return val.replace(srch.group(0), to_replace, 1)
            return val

        if (
            element[0] == "source"
            and isinstance(element[1], str)
            and len(re.split(r"\r?\n", element[1])) > 1
        ):
            element[1] = [
                _replace_once(regexes["number"], rew(x), "")
                for x in re.split(r"\r?\n", element[1])
            ]

        # typogrify

        if element[0] != "date":
            element[1] = typotools.recursive_typography(element[1])

    if debug:
        with codecs.open("debug_5.json", "w", "utf8") as f:
            f.write(json.dumps(structure, ensure_ascii=False, indent=4))

    # 6.

    final_structure = []
    current_question = {}

    for element in structure:
        if (
            element[0]
            in set(["number", "tour", "tourrev", "question", "meta"])
            and "question" in current_question
        ):
            if defaultauthor and "author" not in current_question:
                current_question["author"] = defaultauthor
            check_question(current_question, logger=logger)
            final_structure.append(["Question", current_question])
            current_question = {}
        if element[0] in QUESTION_LABELS:
            if element[0] in current_question:
                logger.warning(
                    "Warning: question {} has multiple {}s.".format(
                        log_wrap(current_question), element[0]
                    )
                )
                if isinstance(element[1], list) and isinstance(
                    current_question[element[0]], str
                ):
                    current_question[element[0]] = [
                        current_question[element[0]]
                    ] + element[1]
                elif isinstance(element[1], str) and isinstance(
                    current_question[element[0]], list
                ):
                    current_question[element[0]].append(element[1])
                elif isinstance(element[1], list) and isinstance(
                    current_question[element[0]], list
                ):
                    current_question[element[0]].extend(element[1])
                elif isinstance(element[0], str) and isinstance(
                    element[1], str
                ):
                    current_question[element[0]] += SEP + element[1]
            else:
                current_question[element[0]] = element[1]
        else:
            final_structure.append([element[0], element[1]])
    if current_question != {}:
        if defaultauthor and "author" not in current_question:
            current_question["author"] = defaultauthor
        check_question(current_question, logger=logger)
        final_structure.append(["Question", current_question])

    # 7.
    try:
        fq = [x[0] for x in final_structure].index("Question")
        headerlabels = [x[0] for x in final_structure[:fq]]
        datedefined = False
        headingdefined = False
        if "date" in headerlabels:
            datedefined = True
        if "heading" in headerlabels or "ljheading" in headerlabels:
            headingdefined = True
        if not headingdefined and final_structure[0][0] == "meta":
            final_structure[0][0] = "heading"
            final_structure.insert(0, ["ljheading", final_structure[0][1]])
        i = 0
        while not datedefined and i < fq:
            if regexes["date2"].search(final_structure[i][1]):
                final_structure[i][0] = "date"
                datedefined = True
            i += 1
    except ValueError:
        pass

    def _replace(obj, val, new_val):
        if isinstance(obj, str):
            return obj.replace(val, new_val)
        elif isinstance(obj, list):
            for i, el in enumerate(obj):
                obj[i] = _replace(el, val, new_val)
            return obj

    def _get_strings(val, list_):
        if isinstance(val, str):
            list_.append(val)
            return
        elif isinstance(val, list):
            for el in val:
                _get_strings(el, list_)


    def _try_extract_field(question, k):
        regex = regexes[k]
        keys = sorted(question.keys())
        to_erase = []
        stop = False
        val = None
        k1_to_replace = None
        for k1 in keys:
            if stop:
                break
            curr_val = question[k1]
            strings = []
            _get_strings(curr_val, strings)
            for string in strings:
                if stop:
                    break
                lines = string.split("\n")
                for i, line in enumerate(lines):
                    srch = regex.search(line)
                    if srch:
                        val = "\n".join([line.replace(srch.group(0), "")] + lines[i + 1 :])
                        to_erase.append(srch.group(0))
                        to_erase.append(val)
                        val = val.strip()
                        k1_to_replace = k1
                        stop = True
                        break
        if val:
            question[k] = val
            for v in to_erase:
                question[k1_to_replace] = _replace(question[k1_to_replace], v, "")
        

    def postprocess_question(question):
        for k in (
            "zachet",
            "nezachet",
            "source",
            "comment",
            "author"
        ):
            if k not in question:
                _try_extract_field(question, k)

    for i, element in enumerate(final_structure):
        if element[0] == "Question":
            postprocess_question(element[1])

    if debug:
        with codecs.open("debug_final.json", "w", "utf8") as f:
            f.write(json.dumps(final_structure, ensure_ascii=False, indent=4))
    return final_structure


class UnknownEncodingException(Exception):
    pass


def chgk_parse_txt(txtfile, encoding=None, defaultauthor="", regexes=None):
    raw = open(txtfile, "rb").read()
    if not encoding:
        if chardet.detect(raw)["confidence"] > 0.7:
            encoding = chardet.detect(raw)["encoding"]
        else:
            raise UnknownEncodingException(
                "Encoding of file {} cannot be verified, "
                "please pass encoding directly via command line "
                "or resave with a less exotic encoding".format(txtfile)
            )
    text = raw.decode(encoding)
    if text[0:10] == "Чемпионат:":
        return chgk_parse_db(text.replace("\r", ""), debug=debug)
    return chgk_parse(text, defaultauthor=defaultauthor, regexes=regexes)


def generate_imgname(target_dir, ext, prefix=""):
    imgcounter = 1
    while os.path.isfile(
        os.path.join(target_dir, "{}{:03}.{}".format(prefix, imgcounter, ext))
    ):
        imgcounter += 1
    return "{}{:03}.{}".format(prefix, imgcounter, ext)


def ensure_line_breaks(tag):
    if tag.text:
        str_ = tag.string or "".join(list(tag.strings))
        if not str_.startswith("\n"):
                str_ = "\n" + str_
        if not str_.endswith("\n"):
            str_ = str_ + "\n"
        tag.insert_before(str_)
    tag.extract()


def chgk_parse_docx(docxfile, defaultauthor="", regexes=None, args=None):
    target_dir = os.path.dirname(os.path.abspath(docxfile))
    if args.image_prefix:
        bn_for_img = os.path.splitext(os.path.basename(docxfile))[0].replace(" ", "_") + "_"
    else:
        bn_for_img = ""
    if args.parsing_engine == "pypandoc":
        txt = pypandoc.convert_file(docxfile, "plain", extra_args=["--wrap=none"])
    else:
        if args.parsing_engine == "pypandoc_html":
            temp_dir = tempfile.mkdtemp()
            html = pypandoc.convert_file(docxfile, "html", extra_args=[f"--extract-media={temp_dir}"])
        else:
            with open(docxfile, "rb") as docx_file:
                html = mammoth.convert_to_html(docx_file).value
        input_docx = (
            html
            .replace("</strong><strong>", "")
            .replace("</em><em>", "")
            .replace("_", "$$$UNDERSCORE$$$")
        )
        bsoup = BeautifulSoup(input_docx, "html.parser")

        if debug:
            with codecs.open(
                os.path.join(target_dir, "debug.pydocx"), "w", "utf8"
            ) as dbg:
                dbg.write(input_docx)

        for tag in bsoup.find_all("style"):
            tag.extract()
        for br in bsoup.find_all("br"):
            br.replace_with("\n")
        for tag in bsoup.find_all("img"):
            if args.parsing_engine == "pypandoc_html":
                src = tag["src"].replace("$$$UNDERSCORE$$$", "_")
                _, ext = os.path.splitext(src)
                imgname = generate_imgname(target_dir, ext[1:], prefix=bn_for_img)
                shutil.copy(src, os.path.join(target_dir, imgname))
                imgpath = os.path.basename(imgname)
            else:
                imgparse = parse("data:image/{ext};base64,{b64}", tag["src"])
                imgname = generate_imgname(target_dir, imgparse["ext"], prefix=bn_for_img)
                with open(os.path.join(target_dir, imgname), "wb") as f:
                    f.write(base64.b64decode(imgparse["b64"]))
                imgpath = os.path.basename(imgname)
            tag.insert_before("(img {})".format(imgpath))
            tag.extract()
        for tag in bsoup.find_all("p"):
            ensure_line_breaks(tag)
        for tag in bsoup.find_all("b"):
            tag.unwrap()
        for tag in bsoup.find_all("strong"):
            tag.unwrap()
        for tag in bsoup.find_all("i"):
            tag.string = "_" + tag.get_text() + "_"
            tag.unwrap()
        for tag in bsoup.find_all("em"):
            tag.string = "_" + tag.get_text() + "_"
            tag.unwrap()
        if args.fix_spans:
            for tag in bsoup.find_all("span"):
                tag.unwrap()
        for h in ["h1", "h2", "h3", "h4"]:
            for tag in bsoup.find_all(h):
                ensure_line_breaks(tag)
        for tag in bsoup.find_all("li"):
            if tag.string:
                tag.string = "- " + tag.string
        for tag in bsoup.find_all("table"):
            table = dashtable.html2md(str(tag))
            tag.insert_before(table)
            tag.extract()
        for tag in bsoup.find_all("hr"):
            tag.extract()
        if args.links == "unwrap":
            for tag in bsoup.find_all("a"):
                tag.unwrap()
        elif args.links == "old":
            for tag in bsoup.find_all("a"):
                if not tag.string or rew(tag.string) == "":
                    tag.extract()
                else:
                    tag.string = tag["href"]
                    tag.unwrap()


        if debug:
            with codecs.open(
                os.path.join(target_dir, "debug_raw.html"), "w", "utf8"
            ) as dbg:
                dbg.write(str(bsoup))
            with codecs.open(
                os.path.join(target_dir, "debug.html"), "w", "utf8"
            ) as dbg:
                dbg.write(bsoup.prettify())

        h = html2text.HTML2Text()
        h.body_width = 0

        if args.parsing_engine == "mammoth_bs_prettify":
            html2text_input = bsoup.prettify()
            txt = h.handle(html2text_input)
        elif args.parsing_engine == "mammoth_hard_unwrap":
            for tag in bsoup:
                if isinstance(tag, bs4.element.Tag):
                    tag.unwrap()
            txt = bsoup.prettify()
        # elif args.parsing_engine == "mammoth":
        #     html2text_input = str(bsoup)
        #     txt = h.handle(html2text_input)
        elif args.parsing_engine in ("pypandoc_html", "mammoth"):
            found = True
            while found:
                found = False
                for tag in bsoup:
                    if isinstance(tag, bs4.element.Tag):
                        tag.unwrap()
                        found = True
            txt = str(bsoup)
    if args.parsing_engine == "pypandoc_html":
        shutil.rmtree(temp_dir)

    txt = (
        txt.replace("\\-", "")
        .replace("\\.", ".")
        .replace("( ", "(")
        .replace("[ ", "[")
        .replace(" )", ")")
        .replace(" ]", "]")
        .replace(" :", ":")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("$$$UNDERSCORE$$$", "\\_")
    )
    txt = re.sub(r"_ *_", "", txt)  # fix bad italic from Word

    if debug:
        with codecs.open(
            os.path.join(target_dir, "debug.debug"), "w", "utf8"
        ) as dbg:
            dbg.write(txt)

    final_structure = chgk_parse(
        txt, defaultauthor=defaultauthor, regexes=regexes
    )
    return final_structure


def chgk_parse_wrapper(path, args, regexes=None):
    abspath = os.path.abspath(path)
    target_dir = os.path.dirname(abspath)
    defaultauthor = ""
    if args.defaultauthor:
        defaultauthor = os.path.splitext(os.path.basename(abspath))[0]
    if os.path.splitext(abspath)[1] == ".txt":
        final_structure = chgk_parse_txt(
            abspath,
            defaultauthor=defaultauthor,
            encoding=args.encoding,
            regexes=regexes,
        )
    elif os.path.splitext(abspath)[1] == ".docx":
        final_structure = chgk_parse_docx(
            abspath, defaultauthor=defaultauthor, regexes=regexes, args=args
        )
    else:
        sys.stderr.write("Error: unsupported file format." + SEP)
        sys.exit()
    outfilename = os.path.join(target_dir, make_filename(abspath))
    logger.info("Output: {}".format(os.path.abspath(outfilename)))
    with codecs.open(outfilename, "w", "utf8") as output_file:
        output_file.write(compose_4s(final_structure, args=args))
    return outfilename


def gui_parse(args, sourcedir):

    global console_mode
    global __file__  # to fix stupid __file__
    __file__ = os.path.abspath(__file__)  # handling in python 2

    global debug
    global logger
    global regexes

    logger = logging.getLogger("parser")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler("parser.log", encoding="utf8")
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    if debug:
        ch.setLevel(logging.INFO)
    else:
        ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s | %(message)s")
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)

    regexes = load_regexes(args.regexes)

    if args.debug:
        debug = True

    if args.filename:
        console_mode = True

    ld = get_lastdir()
    if args.parsedir:
        if os.path.isdir(args.filename):
            ld = args.filename
            set_lastdir(ld)
            for filename in os.listdir(args.filename):
                if filename.endswith((".docx", ".txt")) and not os.path.isfile(
                    os.path.join(args.filename, make_filename(filename))
                ):
                    outfilename = chgk_parse_wrapper(
                        os.path.join(args.filename, filename),
                        args,
                        regexes=regexes,
                    )
                    logger.info(
                        "{} -> {}".format(
                            filename, os.path.basename(outfilename)
                        )
                    )
            input("Press Enter to continue...")

        else:
            print("No directory specified.")
            sys.exit(0)
    else:
        if args.filename:
            ld = os.path.dirname(os.path.abspath(args.filename))
            set_lastdir(ld)
        if not args.filename:
            print("No file specified.")
            sys.exit(0)

        outfilename = chgk_parse_wrapper(args.filename, args, regexes=regexes)
        if outfilename and not console_mode:
            print(
                "Please review the resulting file {}:".format(
                    make_filename(args.filename)
                )
            )
            subprocess.call(
                shlex.split('{} "{}"'.format(TEXTEDITOR, outfilename))
            )
            input("Press Enter to continue...")
        if args.passthrough:
            cargs = DefaultNamespace()
            cargs.action = "compose"
            cargs.filename = outfilename
            gui_compose(cargs)


def main():
    print("This program was not designed to run standalone.")
    input("Press Enter to continue...")


if __name__ == "__main__":
    main()
