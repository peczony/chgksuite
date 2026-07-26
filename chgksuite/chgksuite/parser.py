import base64
import datetime
import hashlib
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib
from typing import ClassVar

import bs4
import chardet
import mammoth
import pypandoc
import requests
import toml
from bs4 import BeautifulSoup
from parse import parse

from chgksuite import typotools
from chgksuite._html2md import html2md
from chgksuite.common import (
    QUESTION_LABELS,
    DefaultNamespace,
    DummyLogger,
    check_question,
    compose_4s,
    get_chgksuite_dir,
    get_lastdir,
    init_logger,
    load_settings,
    log_wrap,
    set_lastdir,
)
from chgksuite.composer import gui_compose
from chgksuite.composer.composer_common import game_to_ext, make_filename
from chgksuite.parser_db import chgk_parse_db
from chgksuite.parsing_engine import python_docx_to_text
from chgksuite.typotools import escape_underscores_except_urls, re_url
from chgksuite.typotools import remove_excessive_whitespace as rew

SEP = "\n"
PANDOC_NOT_FOUND_MESSAGE = "pandoc not found, installing..."
EDITORS = {
    "win32": "notepad",
    "linux2": "xdg-open",  # python2
    "linux": "xdg-open",  # python3
    "darwin": "open -t",
}


def _is_pandoc_unavailable_error(exc):
    return isinstance(exc, OSError) and "No pandoc was found" in str(exc)


def _install_pandoc():
    if not hasattr(pypandoc, "install_pandoc"):
        pypandoc.install_pandoc = pypandoc.download_pandoc
    pypandoc.install_pandoc()
    if hasattr(pypandoc, "clean_pandocpath_cache"):
        pypandoc.clean_pandocpath_cache()


def _pypandoc_convert_file(*args, **kwargs):
    try:
        return pypandoc.convert_file(*args, **kwargs)
    except OSError as exc:
        if not _is_pandoc_unavailable_error(exc):
            raise
        print(PANDOC_NOT_FOUND_MESSAGE)
        _install_pandoc()
        return pypandoc.convert_file(*args, **kwargs)


def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0] + indices, indices + [None])]


def load_regexes(regexfile):
    with open(regexfile, "r", encoding="utf-8") as f:
        regexes = json.loads(f.read())
    return {k: re.compile(v) for k, v in regexes.items()}


DATE_RE1 = re.compile("[0-9]{2}\\.[0-9]{2}\\.[0-9]{4}")
DATE_RE2 = re.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}")


def check_date(match, parse_string):
    try:
        parsed = (
            datetime.datetime.strptime(match.group(0), parse_string)
            .replace(tzinfo=datetime.timezone.utc)
            .date()
        )
        today = datetime.datetime.now().astimezone().date()
        return bool(parsed.year >= 1980 and (parsed < today or (parsed - today).days <= 365))
    except (TypeError, ValueError):
        return False


def search_for_date(str_):
    for match in DATE_RE1.finditer(str_):
        if check_date(match, "%d.%m.%Y"):
            return match
    for match in DATE_RE2.finditer(str_):
        if check_date(match, "%Y-%m-%d"):
            return match


class ChgkParser:
    BADNEXTFIELDS: ClassVar[set] = {"question", "answer"}
    RE_NUM = re.compile("^([0-9]+)\\.?$")
    RE_NUM_START = re.compile("^([0-9]+)\\.")
    ZERO_PREFIXES = ("Нулевой вопрос", "Разминочный вопрос")
    TOUR_NUMBERS_AS_WORDS = (
        "Первый",
        "Второй",
        "Третий",
        "Четвертый",
        "Пятый",
        "Шестой",
        "Седьмой",
        "Восьмой",
        "Девятый",
        "Десятый",
    )

    def __init__(self, defaultauthor=None, args=None, logger=None):
        self.defaultauthor = defaultauthor
        args = args or DefaultNamespace()
        self.regexes = load_regexes(args.regexes)
        self.logger = logger or init_logger("parser")
        self.args = args
        with open(self.args.labels_file, encoding="utf8") as f:
            self.labels = toml.load(f)
        question_label = self.labels["question_labels"]["question"]
        if self.args.language in ("uz", "uz_cyr"):
            self.question_stub = f"{{}} – {question_label}."
        else:
            self.question_stub = f"{question_label} {{}}."
        if self.args.language == "en":
            self.args.typography_quotes = "off"

    def _setup_image_cache(self):
        """Setup image download cache directory and load existing cache"""
        if not hasattr(self, "_image_cache"):
            self.image_cache_dir = os.path.join(
                get_chgksuite_dir(), "downloaded_images"
            )
            os.makedirs(self.image_cache_dir, exist_ok=True)

            self.image_cache_file = os.path.join(
                get_chgksuite_dir(), "image_download_cache.json"
            )
            if os.path.isfile(self.image_cache_file):
                try:
                    with open(self.image_cache_file, encoding="utf8") as f:
                        self._image_cache = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._image_cache = {}
            else:
                self._image_cache = {}

    def _download_image(self, url):
        """Download image from URL and return local filename"""
        self._setup_image_cache()
        url = url.replace("\\", "")

        # Check cache first
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        if url_hash in self._image_cache:
            cached_filename = self._image_cache[url_hash]
            cached_path = os.path.join(self.image_cache_dir, cached_filename)
            if os.path.isfile(cached_path):
                return cached_path

        # Determine file extension
        parsed_url = urllib.parse.urlparse(url)
        path_lower = parsed_url.path.lower()
        ext = None
        for image_ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg"]:
            if path_lower.endswith(image_ext):
                ext = image_ext
                break

        if not ext:
            # Try to guess from URL structure
            if any(
                img_ext in path_lower
                for img_ext in [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".webp",
                    ".gif",
                    ".bmp",
                    ".svg",
                ]
            ):
                for image_ext in [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".webp",
                    ".gif",
                    ".bmp",
                    ".svg",
                ]:
                    if image_ext in path_lower:
                        ext = image_ext
                        break
            else:
                ext = ".jpg"  # Default extension

        filename = url_hash + ext
        filepath = os.path.join(self.image_cache_dir, filename)

        try:
            self.logger.info(f"Downloading image from {url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "image/png,image/jpeg,image/webp,image/gif,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
            response = requests.get(url, timeout=30, stream=True, headers=headers)
            response.raise_for_status()
            time.sleep(0.5)  # rate limiting

            with open(filepath, "wb") as f:
                f.writelines(response.iter_content(chunk_size=8192))

            # Update cache
            self._image_cache[url_hash] = filename
            with open(self.image_cache_file, "w", encoding="utf8") as f:
                json.dump(self._image_cache, f, indent=2, sort_keys=True)

            return filepath

        except Exception:
            self.logger.exception(f"Failed to download image from {url}")
            return None

    def _process_images_in_text(self, text):
        """Process text to find image URLs and replace them with local references"""
        if not text or not getattr(self.args, "download_images", False):
            return text

        if isinstance(text, list):
            return [self._process_images_in_text(item) for item in text]

        if not isinstance(text, str):
            return text

        # Find all URLs in the text
        for match in re_url.finditer(text):
            url = match.group(0)
            url_lower = url.lower()

            # Check if it's a direct image URL
            if any(
                url_lower.endswith(ext)
                for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg"]
            ):
                local_filename = self._download_image(url)
                if local_filename:
                    # Replace URL with chgksuite image syntax
                    img_reference = f"(img {local_filename})"
                    text = text.replace(url, img_reference)

        return text

    def _process_question_images(self, question):
        """Process a question dict to download images from URLs"""
        if not getattr(self.args, "download_images", False):
            return

        # Process all fields except 'source'
        for field in question:
            if field != "source":
                question[field] = self._process_images_in_text(question[field])

    def merge_to_previous(self, index):
        target = index - 1
        if self.structure[target][1]:
            self.structure[target][1] = (
                self.structure[target][1] + SEP + self.structure.pop(index)[1]
            )
        else:
            self.structure[target][1] = self.structure.pop(index)[1]

    def merge_to_next(self, index):
        target = self.structure.pop(index)
        self.structure[index][1] = target[1] + SEP + self.structure[index][1]

    def find_next_fieldname(self, index):
        target = index + 1
        if target < len(self.structure):
            while target < len(self.structure) - 1 and self.structure[target][0] == "":
                target += 1
            return self.structure[target][0]

    # Structural markers that must not be swallowed by the question/answer
    # merge — a "Бой N" between a stray numbered regulation item and a real
    # answer below indicates the numbered item is NOT the question.
    HARD_BOUNDARIES = frozenset(
        {"battle", "section", "tour", "tourrev", "heading", "editor", "date"}
    )

    def merge_y_to_x(self, x, y):
        i = 0
        while i < len(self.structure):
            if self.structure[i][0] == x:
                while (
                    i + 1 < len(self.structure)
                    and self.structure[i + 1][0] != y
                    and self.structure[i + 1][0] not in self.HARD_BOUNDARIES
                ):
                    self.merge_to_previous(i + 1)
            i += 1

    def merge_to_x_until_nextfield(self, x):
        i = 0
        while i < len(self.structure):
            if self.structure[i][0] == x:
                while (
                    i + 1 < len(self.structure)
                    and self.structure[i + 1][0] == ""
                    and self.find_next_fieldname(i) not in self.BADNEXTFIELDS
                ):
                    self.merge_to_previous(i + 1)
            i += 1

    def dirty_merge_to_x_until_nextfield(self, x):
        i = 0
        while i < len(self.structure):
            if self.structure[i][0] == x:
                while i + 1 < len(self.structure) and self.structure[i + 1][0] == "":
                    self.merge_to_previous(i + 1)
            i += 1

    def remove_formatting(self, str_):
        return str_.replace("_", "")

    def apply_regexes(self, st):
        i = 0
        regexes = self.regexes
        # SI-specific regexes (si_*) belong to SiParser only — including them
        # here would e.g. match "Бой N" and drop the battle marker since
        # compose_4s has no mapping for ``si_battle``.
        excluded = {"number", "date2", "handout_short"} | {
            k for k in regexes if k.startswith("si_")
        }
        while i < len(st):
            matching_regexes = {
                (
                    regex,
                    regexes[regex].search(self.remove_formatting(st[i][1])).start(0),
                )
                for regex in set(regexes) - excluded
                if regexes[regex].search(self.remove_formatting(st[i][1]))
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

    @classmethod
    def _replace(cls, obj, val, new_val):
        if isinstance(obj, str):
            return obj.replace(val, new_val).strip()
        elif isinstance(obj, list):
            for i, el in enumerate(obj):
                obj[i] = cls._replace(el, val, new_val)
            return obj

    def _get_strings(self, val, list_):
        if isinstance(val, str):
            list_.append(val)
            return
        elif isinstance(val, list):
            for el in val:
                self._get_strings(el, list_)

    def _get_strings_joined(self, val):
        strings = []
        self._get_strings(val, strings)
        return "\n".join(strings)

    def _try_extract_field(self, question, k):
        regex = self.regexes[k]
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
            self._get_strings(curr_val, strings)
            for string in strings:
                if stop:
                    break
                lines = string.split("\n")
                for i, line in enumerate(lines):
                    srch = regex.search(line)
                    if srch:
                        val = "\n".join(
                            [line.replace(srch.group(0), "")] + lines[i + 1 :]
                        )
                        to_erase.append(srch.group(0))
                        to_erase.append(val)
                        val = val.strip()
                        k1_to_replace = k1
                        stop = True
                        break
        if val:
            question[k] = val
            for v in to_erase:
                question[k1_to_replace] = self._replace(question[k1_to_replace], v, "")

    def postprocess_question(self, question):
        if (
            "number" in question
            and isinstance(question["number"], str)
            and not question["number"].strip()
        ):
            question.pop("number")
        question_str = self._get_strings_joined(question["question"])
        for prefix in self.ZERO_PREFIXES:
            if question_str.startswith(prefix):
                question["question"] = self._replace(question["question"], prefix, "")
                question["number"] = 0
                question_str = self._get_strings_joined(question["question"])
        for k in ("zachet", "nezachet", "source", "comment", "author"):
            if k not in question:
                self._try_extract_field(question, k)
        question_str = self._get_strings_joined(question["question"])
        handout = self.labels["question_labels"]["handout"]
        srch = re.search(f"{handout}:([ \n]+)\\[", question_str, flags=re.DOTALL)
        if srch:
            question["question"] = self._replace(
                question["question"],
                srch.group(0),
                f"[{handout}:" + srch.group(1),
            )

    def get_single_number_lines(self):
        result = []
        for i, x in enumerate(self.structure):
            if x[0] != "":
                continue
            txt = x[1].strip()
            srch = self.RE_NUM.search(txt)
            if srch:
                num = int(srch.group(1))
                result.append((i, x, num))
        return result

    def patch_single_number_line(self, line):
        index, _, num = line
        self.structure[index] = ["question", self.question_stub.format(num)]

    def process_single_number_lines(self):
        if self.args.single_number_line_handling == "off":
            return
        if self.args.single_number_line_handling == "smart":
            for el in self.structure:
                if el[0] == "question":
                    return
            single_number_lines = self.get_single_number_lines()
            if not single_number_lines:
                return
            frac = len(self.structure) / len(single_number_lines)
            if not (4.0 <= frac <= 13.0):
                return
            prev = None
            for line in single_number_lines:
                if not prev or (line[2] - prev[2] <= 3 and line[0] - prev[0] > 1):
                    self.patch_single_number_line(line)
                    prev = line
        elif self.args.single_number_line_handling == "on":
            single_number_lines = self.get_single_number_lines()
            for line in single_number_lines:
                self.patch_single_number_line(line)

    def do_enumerate_hack(self):
        # Look-ahead window: only promote "N. text" to question if an answer
        # (or another question/handout) shows up before we leave the local
        # block. Without this, a regulation block like "1. Бои Double
        # Elimination… 2. Все бои…" right after the last question's author
        # would be promoted to a stray question.
        LOOKAHEAD = 12
        BLOCK_END = {"editor", "tour", "tourrev", "date", "heading", "battle"}
        prev_nonzero_type = None
        for i, el in enumerate(self.structure):
            if (
                not el[0]
                and prev_nonzero_type is not None
                and prev_nonzero_type == "author"
                and self.RE_NUM_START.search(el[1])
            ):
                has_answer_soon = False
                for j in range(i + 1, min(i + 1 + LOOKAHEAD, len(self.structure))):
                    nt = self.structure[j][0]
                    if nt in ("answer", "handout", "question"):
                        has_answer_soon = True
                        break
                    if nt in BLOCK_END:
                        break
                if has_answer_soon:
                    el[0] = "question"
                    el[1] = self.RE_NUM_START.sub("", el[1]).strip()
            if el[0]:
                prev_nonzero_type = el[0]

    def parse(self, text):
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

        regexes = self.regexes
        debug = self.args.debug
        logger = self.logger

        if self.defaultauthor:
            logger.info(
                f"The default author is {log_wrap(self.defaultauthor)}. "
                "Missing authors will be substituted with them"
            )

        if debug:
            with open("debug_0.txt", "w", encoding="utf-8") as f:
                f.write(text)

        # 1.
        sep = "\r\n" if "\r\n" in text else "\n"

        if ("«" in text or "»" in text) and self.args.typography_quotes == "smart":
            typography_quotes = "smart_disable"
        else:
            typography_quotes = self.args.typography_quotes
        if "\u0301" in text and self.args.typography_accents == "smart":
            typography_accents = "smart_disable"
        else:
            typography_accents = self.args.typography_accents

        fragments = [
            [["", rew(xx)] for xx in x.split(sep) if xx] for x in text.split(sep + sep)
        ]

        for fragment in fragments:
            self.apply_regexes(fragment)
            elements = {x[0] for x in fragment}
            if "answer" in elements and not fragment[0][0]:
                fragment[0][0] = "question"
        self.structure = list(itertools.chain(*fragments))
        self.do_enumerate_hack()
        for el in self.structure:
            if el[0] == "handout":
                el[0] = "question"
        i = 0

        if debug:
            with open("debug_1.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.structure, ensure_ascii=False, indent=4))

        self.process_single_number_lines()

        # hack for https://gitlab.com/peczony/chgksuite/-/issues/23; TODO: make less hacky
        for i, element in enumerate(self.structure):
            if (
                "Дуплет." in element[1].split()
                or "Блиц." in element[1].split()
                and element[0] != "question"
                and (i == 0 or self.structure[i - 1][0] != "question")
            ):
                element[0] = "question"

        if debug:
            with open("debug_1a.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.structure, ensure_ascii=False, indent=4))

        # 2.

        self.merge_y_to_x("question", "answer")
        self.merge_to_x_until_nextfield("answer")
        self.merge_to_x_until_nextfield("comment")

        if debug:
            with open("debug_2.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.structure, ensure_ascii=False, indent=4))

        # 3.

        i = 0
        while i < len(self.structure):
            if self.structure[i][0] == "answer" and self.structure[i - 1][0] not in (
                "question",
                "newquestion",
            ):
                self.structure.insert(i, ["newquestion", ""])
                i = 0
            i += 1

        i = 0
        while i < len(self.structure) - 1:
            if self.structure[i][0] == "" and self.structure[i + 1][0] == "newquestion":
                self.merge_to_next(i)
                if regexes["number"].search(rew(self.structure[i][1])) and not regexes[
                    "number"
                ].search(rew(self.structure[i - 1][1])):
                    self.structure[i][0] = "question"
                    self.structure[i][1] = regexes["number"].sub(
                        "", rew(self.structure[i][1])
                    )
                    try:
                        num = regexes["number"].search(rew(self.structure[i][1]))
                        if num:
                            self.structure.insert(
                                i,
                                [
                                    "number",
                                    int(num.group(0)),
                                ],
                            )
                    except Exception:
                        logger.exception("exception while renumbering questions")
                i = 0
            i += 1

        for element in self.structure:
            if element[0] == "newquestion":
                element[0] = "question"

        self.dirty_merge_to_x_until_nextfield("source")

        for _id, element in enumerate(self.structure):
            if (
                element[0] == "author"
                and re.search(
                    r"^{}$".format(regexes["author"].pattern), rew(element[1])
                )
                and _id + 1 < len(self.structure)
            ):
                self.merge_to_previous(_id + 1)

        self.merge_to_x_until_nextfield("zachet")
        self.merge_to_x_until_nextfield("nezachet")

        if debug:
            with open("debug_3.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.structure, ensure_ascii=False, indent=4))

        # 4.

        self.structure = [x for x in self.structure if [x[0], rew(x[1])] != ["", ""]]

        if self.structure[0][0] == "" and regexes["number"].search(
            rew(self.structure[0][1])
        ):
            self.merge_to_next(0)

        if debug:
            with open("debug_3a.json", "w", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        list(enumerate(self.structure)), ensure_ascii=False, indent=4
                    )
                )

        idx = 0
        cycle = -1
        while idx < len(self.structure):
            cycle += 1
            element = self.structure[idx]
            if element[0] == "":
                element[0] = "meta"
            if element[0] in regexes and element[0] not in [
                "tour",
                "tourrev",
                "editor",
                "battle",
            ]:
                if element[0] == "question":
                    try:
                        num = regexes["question"].search(element[1])
                        if num and num.group("number"):
                            self.structure.insert(idx, ["number", num.group("number")])
                            idx += 1
                    except Exception:
                        num = None
                        logger.exception(
                            f"exception at setting number\nQuestion: {element[1]}"
                        )
                    if (num is None or num and not num.group("number")) and (
                        ("нулевой вопрос" in element[1].lower())
                        or ("разминочный вопрос" in element[1].lower())
                    ):
                        self.structure.insert(idx, ["number", "0"])
                        idx += 1
                if element[0] == "question":
                    lines = element[1].split(SEP)
                    for i, line in enumerate(lines):
                        if regexes["question"].search(line):
                            lines[i] = regexes["question"].sub("", line, 1)
                    element[1] = SEP.join([x.strip() for x in lines if x.strip()])
                    before_replacement = None
                else:
                    before_replacement = element[1]
                    element[1] = regexes[element[0]].sub("", element[1], 1)
                element[1] = element[1].removeprefix(SEP)
                # TODO: переделать корявую обработку авторки на нормальную
                if (
                    element[0] == "author"
                    and before_replacement
                    and "авторка:" in before_replacement.lower()
                ):
                    element[1] = "!!Авторка" + element[1]
            idx += 1

        if debug:
            with open("debug_4.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.structure, ensure_ascii=False, indent=4))

        # 5.

        for _id, element in enumerate(self.structure):
            # remove question numbers

            if element[0] == "question":
                try:
                    num = regexes["question"].search(element[1])
                    if num:
                        self.structure.insert(_id, ["number", num.group("number")])
                except Exception:
                    logger.exception("exception while extracting question number")
                element[1] = regexes["question"].sub("", element[1])

            # detect inner lists
            mo = {
                m for m in re.finditer(r"(\s+|^)(\d+)[\.\)]\s*(?!\d)", element[1], re.UNICODE)
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
                    positions = [x[2] for x in list_candidate]
                    positions_monotonic = all(
                        positions[i] < positions[i + 1]
                        for i in range(len(positions) - 1)
                    )
                    if not positions_monotonic:
                        pass  # false positive: a duplicate number matched at wrong position
                    elif element[0] != "question" or (
                        element[0] == "question"
                        and "дуплет" in element[1].lower()
                        or "блиц" in element[1].lower()
                    ):
                        part = partition(element[1], positions)
                        lc = 0
                        while lc < len(list_candidate):
                            part[lc + 1] = part[lc + 1].replace(
                                list_candidate[lc][1], "", 1
                            )
                            lc += 1
                        element[1] = [part[0], part[1:]] if part[0] != "" else part[1:]

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
                element[1] = typotools.recursive_typography(
                    element[1],
                    accents=typography_accents,
                    dashes=self.args.typography_dashes,
                    quotes=typography_quotes,
                    wsp=self.args.typography_whitespace,
                    percent=self.args.typography_percent,
                )

        if debug:
            with open("debug_5.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(self.structure, ensure_ascii=False, indent=4))

        # 6.

        final_structure = []
        current_question = {}

        for element in self.structure:
            if (
                element[0]
                in {"number", "tour", "tourrev", "question", "meta", "editor"}
                and "question" in current_question
            ):
                if self.defaultauthor and "author" not in current_question:
                    current_question["author"] = self.defaultauthor
                self._process_question_images(current_question)
                check_question(current_question, logger=logger)
                final_structure.append(["Question", current_question])
                current_question = {}
            if element[0] in QUESTION_LABELS:
                if element[0] in current_question:
                    logger.warning(
                        f"Warning: question {log_wrap(current_question)} has multiple {element[0]}s."
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
                    elif isinstance(element[0], str) and isinstance(element[1], str):
                        current_question[element[0]] += SEP + element[1]
                else:
                    current_question[element[0]] = element[1]
            else:
                final_structure.append([element[0], element[1]])
        if current_question != {}:
            if self.defaultauthor and "author" not in current_question:
                current_question["author"] = self.defaultauthor
            self._process_question_images(current_question)
            check_question(current_question, logger=logger)
            final_structure.append(["Question", current_question])

        if debug:
            with open("debug_6.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(final_structure, ensure_ascii=False, indent=4))

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
            def make_date(i):
                # a heading stays a heading; the date it contains becomes its
                # own element (pre-existing behaviour, previously via the
                # ljheading copy that used to absorb this conversion)
                if final_structure[i][0] == "heading":
                    final_structure.insert(i, ["date", final_structure[i][1]])
                else:
                    final_structure[i][0] = "date"

            i = 0
            while not datedefined and i < fq:
                srch = regexes["date2"].search(final_structure[i][1])
                if srch and len(srch.group(0)) >= len(final_structure[i][1]) / 10:
                    make_date(i)
                    datedefined = True
                    break
                srch = search_for_date(final_structure[i][1])
                if srch and len(srch.group(0)) >= len(final_structure[i][1]) / 10:
                    make_date(i)
                    datedefined = True
                    break
                i += 1
        except ValueError:
            pass

        tour_cnt = 0
        for i, element in enumerate(final_structure):
            if element[0] == "Question":
                self.postprocess_question(element[1])
            elif element[0] == "tour" and self.args.tour_numbers_as_words == "on":
                element[1] = f"{self.TOUR_NUMBERS_AS_WORDS[tour_cnt]} тур"
                tour_cnt += 1
            elif element[0] not in ["Question", "source"] and getattr(
                self.args, "download_images", False
            ):
                # Process images in metadata fields (excluding source)
                element[1] = self._process_images_in_text(element[1])

        if debug:
            with open("debug_final.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(final_structure, ensure_ascii=False, indent=4))
        return final_structure


def chgk_parse(text, defaultauthor=None, args=None):
    parser = ChgkParser(defaultauthor=defaultauthor, args=args)
    parsed = parser.parse(text)
    return parsed


class UnknownEncodingException(Exception):
    pass


def chgk_parse_txt(txtfile, encoding=None, defaultauthor="", args=None, logger=None):
    with open(txtfile, "rb") as f:
        raw = f.read()
    # Fix corrupted line endings at byte level before decoding
    if b"\r\r\n" in raw:
        raw = raw.replace(b"\r\r\n", b"\n")
    if not encoding:
        if chardet.detect(raw)["confidence"] > 0.7:
            encoding = chardet.detect(raw)["encoding"]
        else:
            raise UnknownEncodingException(
                f"Encoding of file {txtfile} cannot be verified, "
                "please pass encoding directly via command line "
                "or resave with a less exotic encoding"
            )
    text = raw.decode(encoding)
    # Normalize any remaining line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text[0:10] == "Чемпионат:":
        return chgk_parse_db(text, debug=args.debug, logger=logger)
    return chgk_parse(
        escape_underscores_except_urls(text),
        defaultauthor=defaultauthor,
        args=args,
    )


def generate_imgname(target_dir, ext, prefix=""):
    imgcounter = 1
    while os.path.isfile(
        os.path.join(target_dir, f"{prefix}{imgcounter:03}.{ext}")
    ):
        imgcounter += 1
    return f"{prefix}{imgcounter:03}.{ext}"


def ensure_line_breaks(tag):
    if tag.text:
        str_ = tag.string or "".join(list(tag.strings))
        if not str_.startswith("\n"):
            tag.insert(0, "\n")
        if not str_.endswith("\n"):
            tag.append("\n")
    tag.unwrap()


def normalize_html_before_flattening(bsoup):
    for li in bsoup.find_all("li"):
        if not li.get_text(strip=True) and not li.find("img"):
            li.extract()
            continue
        for p in li.find_all("p", recursive=False):
            p.unwrap()


def normalize_docx_spacing(text):
    lines = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        if body.lstrip().startswith("|"):
            lines.append(line)
            continue
        body = body.replace("\t", " ")
        body = re.sub(r"(?<=\S) {2,}(?=\S)", " ", body)
        body = re.sub(r" +$", "", body)
        lines.append(body + newline)
    return "".join(lines)


# --- SI (Своя Игра) parsing --------------------------------------------------

# Language-neutral structural markers for SI.
# Synthetic heading markers injected by ``docx_to_text`` when parsing SI DOCX.
_SI_RE_STYLE_HEADING = re.compile(r"^\$\$H(\d)\$\$\s*(.*)")
# Question numbers in SI are point values, not sequential — same in every language.
_SI_RE_QUESTION_NUM = re.compile(r"^(\d+)\.\s+")
_SI_RE_QUESTION_NUM_ONLY = re.compile(r"^(\d+)\.?$")
_SI_QUESTION_NUMBERS = {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
# Inline theme header with author in parens: "2. Ноль (Давид Эджибия)".
# Theme index is small (not a question point value) and the line ends with
# "(...)" holding the author. Used when DOCX styling did not mark the header
# as a real heading.
_SI_RE_THEME_NUMBERED_AUTHORED = re.compile(r"^(\d+)\.\s+(.+\([^)]+\))\s*$")

# Languages whose SI-specific regex keys are localized in regexes_{lang}.json.
_SI_REGEX_KEYS = (
    "si_theme",
    "si_theme_comment",
    "si_battle",
    "si_battle_numbered",
    "si_your_themes",
    "si_round_name",
)

_TROIKA_RE_REDUNDANT_THEME_PREFIX = re.compile(r"(?i)^ТЕМА[\.:]\s*")
_TROIKA_RE_THEME_NUMBER_BEFORE_REDUNDANT_PREFIX = re.compile(
    r"(?i)^ТЕМА\s+\d+(?:\s*\([^)]+\))?[\.:]\s*(?=ТЕМА[\.:])"
)
_TROIKA_RE_THEME = re.compile(
    r"(?i)^ТЕМА(?:\s+\d+(?:\s*\([^)]+\))?)?[\.:]\s*.+"
)
_TROIKA_RE_SECTION = re.compile(r"(?i)^ГРУППОВОЙ\s+ЭТАП\s+\d+\s*$")
# "Темы за N балл(а/ов)" — point-value section header separating theme blocks.
_TROIKA_RE_POINTS_SECTION = re.compile(r"(?i)^ТЕМЫ\s+ЗА\s+\d+\s+балл\S*\s*$")
_TROIKA_RE_BATTLE = re.compile(r"(?i)^БОЙ\s+(?:\d+|[IVXLCDM]+)\s*$")
_TROIKA_RE_FINAL = re.compile(r"(?i)^\d+/\d+\s+ФИНАЛА\.?\s*$")
_TROIKA_RE_QUESTION_NUM = re.compile(r"^(\d+)\.?\s+")
_TROIKA_RE_QUESTION_NUM_ONLY = re.compile(r"^(\d+)\.?$")
_TROIKA_QUESTION_NUMBERS = {1, 2, 3}
# "Мультифора" Troika variant: questions carry an "N.M." marker (N = theme index,
# M = question index within the theme), optionally spelled out as "Вопрос N.M." or,
# in the reserve pool, "ЗапN.M.". Themes are written as bare "N. Name" headers
# instead of a heading-styled line. Capture group 1 is the within-theme question
# index (M), used as the question number. The trailing dot after M is required so
# bare "N. Name" theme headers are not mistaken for questions.
_TROIKA_RE_MULTIFORA_QUESTION = re.compile(
    r"(?i)^(?:ВОПРОС\s+|ЗАП)?\d+\s*\.\s*(\d+)\s*\.\s*"
)
# Detects the variant anywhere in the document (optionally behind a heading marker).
_TROIKA_RE_MULTIFORA_DETECT = re.compile(
    r"(?im)^\s*(?:\$\$H\d\$\$\s*)?(?:ВОПРОС\s+|ЗАП)?\d+\s*\.\s*\d+\s*\."
)
# Bare numbered theme header "3. Вокруг войны 1812 года" (Мультифора mode only).
_TROIKA_RE_NUMBERED_THEME = re.compile(r"^\d+\.\s+\S")
# Reserve pool: a bare "Запас" section header and "Запас-N. Name" theme headers.
_TROIKA_RE_RESERVE_SECTION = re.compile(r"(?i)^ЗАПАС\s*$")
_TROIKA_RE_RESERVE_THEME = re.compile(r"(?i)^ЗАПАС\s*-\s*\d+\s*\.\s*.+")
_TROIKA_RE_SOURCE_ITEM = re.compile(r"^(\d+)[\.\)]\s+")
_TROIKA_RE_HOST_NOTE = re.compile(
    r"(?i)^\[?(?:Ведущему\b|Комментарий\s+ведущему\b)"
)


def _normalize_troika_theme_text(text):
    text = _TROIKA_RE_THEME_NUMBER_BEFORE_REDUNDANT_PREFIX.sub(
        "", text, count=1
    ).strip()
    return _TROIKA_RE_REDUNDANT_THEME_PREFIX.sub("", text, count=1).strip()


class SiParser:
    """Parse SI (Своя Игра) plain text into a 4s structure."""

    _RE_LEADING_NUM = re.compile(r"^\d+[\.\)]\s*")
    _RE_AUTHOR_GRATITUDE_META = re.compile(r"(?i)^Автор(?:ы|ка)?\s+благодар")
    _RE_THEMES_HEADER = re.compile(r"тем[ыа]\s*:?$", re.IGNORECASE)
    _RE_URL_LIKE = re.compile(
        r"https?://|www\.|/|\.(?:ru|com|net|org|io|info|edu|su|by|ua|kz)\b"
    )
    _STRUCTURAL_TYPES = (
        "battle",
        "round",
        "section",
        "theme",
        "heading",
        "editor",
        "date",
        "meta",
    )

    def __init__(self, args=None, logger=None):
        self.args = args or DefaultNamespace()
        self.logger = logger or init_logger("parser")
        self.regexes = load_regexes(self.args.regexes)
        # Field labels shared with ChGK; we only accept them at line-start.
        r = self.regexes
        self.re_answer = r["answer"]
        self.re_zachet = r["zachet"]
        self.re_nezachet = r["nezachet"]
        self.re_comment = r["comment"]
        self.re_author = r["author"]
        self.re_source = r["source"]
        self.re_editor = r["editor"]
        self.re_theme = r["si_theme"]
        self.re_theme_comment = r["si_theme_comment"]
        self.re_battle = r["si_battle"]
        self.re_battle_numbered = r["si_battle_numbered"]
        self.re_your_themes = r["si_your_themes"]
        self.re_round_name = r["si_round_name"]
        # Field labels that, when encountered as H3-styled headings, indicate
        # the preceding theme was actually a question (authored with wrong style).
        self._field_promote_regexes = (
            self.re_answer,
            self.re_zachet,
            self.re_nezachet,
            self.re_comment,
            self.re_source,
        )

    def parse(self, text):
        self._init_state(text)
        for line in text.split("\n"):
            self._handle_line(line)
        self._flush()
        return self._build_final_structure()

    # --- State / typography --------------------------------------------------

    def _init_state(self, text):
        self.structure = []
        self.current_field = None
        self.current_content = ""
        self.heading_found = False
        self.in_theme_list = False
        self.after_theme = False
        # Full H3 heading text of the most recent theme — used to retroactively
        # promote a theme to a question when a field label (Ответ:/...) follows
        # it; the docx styled the question with a heading by mistake.
        self.last_theme_heading = None

        if ("«" in text or "»" in text) and self.args.typography_quotes == "smart":
            self.typography_quotes = "smart_disable"
        else:
            self.typography_quotes = getattr(self.args, "typography_quotes", "on") or "on"
        if "\u0301" in text and self.args.typography_accents == "smart":
            self.typography_accents = "smart_disable"
        else:
            self.typography_accents = getattr(self.args, "typography_accents", "on") or "on"

    def _apply_typo(self, s):
        return typotools.recursive_typography(
            s,
            accents=self.typography_accents,
            dashes=getattr(self.args, "typography_dashes", "on"),
            quotes=self.typography_quotes,
            wsp=getattr(self.args, "typography_whitespace", "on"),
            percent=getattr(self.args, "typography_percent", "on"),
        )

    def _flush(self):
        if self.current_field and self.current_content.strip():
            self.structure.append(
                [self.current_field, self._apply_typo(rew(self.current_content))]
            )
        self.current_field = None
        self.current_content = ""

    def _promote_last_theme_to_question(self):
        """If the previous element is a tentatively tagged theme whose heading
        started with an SI point value, rewrite it as [number, question]."""
        if self.last_theme_heading is None:
            return
        if not self.structure or self.structure[-1][0] != "theme":
            self.last_theme_heading = None
            return
        m_qnum = _SI_RE_QUESTION_NUM.search(self.last_theme_heading)
        if not m_qnum or int(m_qnum.group(1)) not in _SI_QUESTION_NUMBERS:
            self.last_theme_heading = None
            return
        num_str = m_qnum.group(1)
        q_text = self.last_theme_heading[m_qnum.end():].strip()
        self.structure[-1:] = [
            ["number", num_str],
            ["question", self._apply_typo(q_text)],
        ]
        self.last_theme_heading = None

    # --- Per-line dispatch ---------------------------------------------------

    def _handle_line(self, line):
        stripped = rew(line)
        if not stripped:
            self.after_theme = False
            return

        m_style = _SI_RE_STYLE_HEADING.search(stripped)
        if m_style:
            heading_text = rew(m_style.group(2))
            if not heading_text:
                return
            # "Ответ:" and similar fields are still fields even when heading-
            # styled by accident. Strip the heading prefix and fall through.
            if self._is_field_label(heading_text):
                self._promote_last_theme_to_question()
                stripped = heading_text
            else:
                self._handle_heading(int(m_style.group(1)), heading_text)
                return

        if self.re_your_themes.search(stripped):
            self._flush()
            self.in_theme_list = True
            self.structure.append(["meta", self._apply_typo(stripped)])
            return

        m_theme = self.re_theme.search(stripped)
        if m_theme:
            self.in_theme_list = False
            self._flush()
            theme_text = m_theme.group(2).strip()
            self.structure.append(["theme", self._apply_typo(theme_text)])
            self.after_theme = True
            return

        if self.in_theme_list:
            if self.structure and self.structure[-1][0] == "meta":
                self.structure[-1][1] += SEP + self._apply_typo(stripped)
            else:
                self.structure.append(["meta", self._apply_typo(stripped)])
            return

        if self.re_theme_comment.search(stripped):
            self._flush()
            self.current_field = "comment"
            self.current_content = self.re_theme_comment.sub("", stripped)
            return

        if self.re_round_name.search(stripped):
            self._flush()
            self.structure.append(["round", self._apply_typo(stripped)])
            return

        if self.re_battle.search(stripped):
            self._flush()
            self.structure.append(["battle", self._apply_typo(stripped)])
            return

        if self.re_battle_numbered.search(stripped) and not self.re_theme.search(stripped):
            self._flush()
            self.structure.append(["battle", self._apply_typo(stripped)])
            return

        if self._dispatch_label(stripped, self.re_editor, "editor", append=True):
            return
        if self._dispatch_author(stripped):
            return
        for regex, field in (
            (self.re_answer, "answer"),
            (self.re_zachet, "zachet"),
            (self.re_nezachet, "nezachet"),
            (self.re_comment, "comment"),
            (self.re_source, "source"),
        ):
            if self._dispatch_label(stripped, regex, field):
                return

        if self._dispatch_question_num(stripped):
            return
        if self._dispatch_question_num_only(stripped):
            return

        if self._dispatch_author_gratitude_meta(stripped):
            return

        # Default: continuation of current field, first heading, or meta.
        if self.current_field:
            self.current_content += SEP + stripped
        elif not self.heading_found:
            self.heading_found = True
            self.structure.append(["heading", self._apply_typo(stripped)])
        else:
            self.structure.append(["meta", self._apply_typo(stripped)])

    def _is_field_label(self, heading_text):
        for r in self._field_promote_regexes:
            m = r.search(heading_text)
            if m and m.start() == 0:
                return True
        return False

    def _handle_heading(self, level, heading_text):
        self._flush()
        self.in_theme_list = False
        if self.re_round_name.search(heading_text):
            self.structure.append(["round", self._apply_typo(heading_text)])
            return
        if self.re_battle.search(heading_text):
            self.structure.append(["battle", self._apply_typo(heading_text)])
            return
        if level == 1:
            self.structure.append(["battle", self._apply_typo(heading_text)])
        elif level == 2:
            if self._RE_THEMES_HEADER.match(heading_text):
                self.in_theme_list = True
            self.structure.append(["meta", self._apply_typo(heading_text)])
        elif level == 3:
            theme_text = self._RE_LEADING_NUM.sub("", heading_text)
            self.structure.append(["theme", self._apply_typo(theme_text)])
            self.last_theme_heading = heading_text
            self.after_theme = True

    def _dispatch_label(self, stripped, regex, field, append=False):
        m = regex.search(stripped)
        if not m or m.start() != 0:
            return False
        self._flush()
        content = regex.sub("", stripped, 1).strip()
        if append:
            self.structure.append([field, self._apply_typo(content)])
        else:
            self.current_field = field
            self.current_content = content
        return True

    def _dispatch_author(self, stripped):
        m = self.re_author.search(stripped)
        if not m or m.start() != 0:
            return False
        self._flush()
        content = self.re_author.sub("", stripped, 1).strip()
        if self.after_theme:
            self.structure.append(["author", self._apply_typo(content)])
        else:
            self.current_field = "author"
            self.current_content = content
        return True

    def _dispatch_author_gratitude_meta(self, stripped):
        if (
            self.current_field != "author"
            or not self._RE_AUTHOR_GRATITUDE_META.search(stripped)
        ):
            return False
        self._flush()
        self.structure.append(["meta", self._apply_typo(stripped)])
        return True

    def _dispatch_question_num(self, stripped):
        m = _SI_RE_QUESTION_NUM.search(stripped)
        if not m:
            return False
        num = int(m.group(1))
        if num in _SI_QUESTION_NUMBERS:
            self._flush()
            self.structure.append(["number", str(num)])
            question_text = stripped[m.end():].strip()
            if question_text:
                self.current_field = "question"
                self.current_content = question_text
            return True
        # Inline theme header "N. Name (Author)" with small N (not a question
        # point value). Skip when mid-source-list: an empty "Источник:" header
        # followed by numbered URLs must not be reclassified as a theme header.
        if self.current_field == "source" and not self.current_content.strip():
            return False
        m_authored = _SI_RE_THEME_NUMBERED_AUTHORED.search(stripped)
        if (
            m_authored
            and num not in _SI_QUESTION_NUMBERS
            and not self._RE_URL_LIKE.search(stripped)
        ):
            self._flush()
            self.in_theme_list = False
            self.structure.append(
                ["theme", self._apply_typo(m_authored.group(2).strip())]
            )
            self.after_theme = True
            return True
        return False

    def _dispatch_question_num_only(self, stripped):
        m = _SI_RE_QUESTION_NUM_ONLY.search(stripped)
        if not m:
            return False
        num = int(m.group(1))
        if num in _SI_QUESTION_NUMBERS:
            self._flush()
            self.structure.append(["number", str(num)])
            self.current_field = "question"
            self.current_content = ""
            return True
        return False

    # --- Packing -------------------------------------------------------------

    def _build_final_structure(self):
        final_structure = []
        current_question = {}

        for element in self.structure:
            etype = element[0]
            if etype in self._STRUCTURAL_TYPES:
                if "question" in current_question:
                    final_structure.append(["Question", current_question])
                    current_question = {}
                final_structure.append(element)
            elif etype == "number":
                if "question" in current_question:
                    final_structure.append(["Question", current_question])
                    current_question = {}
                current_question["number"] = element[1]
            elif etype in QUESTION_LABELS:
                if not current_question and etype not in ("question", "number"):
                    final_structure.append(element)
                elif etype in current_question:
                    if isinstance(current_question[etype], str) and isinstance(
                        element[1], str
                    ):
                        current_question[etype] += SEP + element[1]
                    else:
                        current_question[etype] = element[1]
                else:
                    current_question[etype] = element[1]
            else:
                if "question" in current_question:
                    final_structure.append(["Question", current_question])
                    current_question = {}
                final_structure.append(element)

        if "question" in current_question:
            final_structure.append(["Question", current_question])

        # Split multi-line source into a list of individual references.
        for element in final_structure:
            if element[0] != "Question":
                continue
            q = element[1]
            if "source" in q and isinstance(q["source"], str):
                source_lines = [s.strip() for s in q["source"].split(SEP) if s.strip()]
                if len(source_lines) > 1:
                    q["source"] = [
                        self._RE_LEADING_NUM.sub("", s) for s in source_lines
                    ]
        return final_structure


def si_parse_text(text, args=None, logger=None):
    """Parse SI plain text into a 4s structure with battle/theme/question elements."""
    return SiParser(args=args, logger=logger).parse(text)


class TroikaParser(SiParser):
    """Parse Troika text into an SI-like battle/theme/question structure."""

    def _init_state(self, text):
        super()._init_state(text)
        self.last_line_blank = False
        self.source_list_mode = False
        # "Мультифора" variant uses explicit "Вопрос N.M." question markers and
        # bare "N. Name" theme headers; detect it up front to switch the meaning
        # of bare numbered lines from question numbers to theme headers.
        self.multifora_mode = bool(_TROIKA_RE_MULTIFORA_DETECT.search(text))

    def _flush(self):
        super()._flush()
        self.source_list_mode = False

    def _handle_line(self, line):
        stripped = rew(line)
        if not stripped:
            self.after_theme = False
            self.last_line_blank = True
            return

        m_style = _SI_RE_STYLE_HEADING.search(stripped)
        heading_level = None
        if m_style:
            heading_level = int(m_style.group(1))
            heading_text = rew(m_style.group(2))
            if not heading_text:
                self.last_line_blank = False
                return
            stripped = heading_text

        for regex, etype in (
            (_TROIKA_RE_SECTION, "section"),
            (_TROIKA_RE_BATTLE, "battle"),
            (_TROIKA_RE_THEME, "theme"),
        ):
            if regex.search(stripped):
                self._flush()
                value = (
                    _normalize_troika_theme_text(stripped)
                    if etype == "theme"
                    else stripped
                )
                self.structure.append([etype, self._apply_typo(value)])
                self.after_theme = etype == "theme"
                self.last_line_blank = False
                return

        if _TROIKA_RE_POINTS_SECTION.search(stripped):
            self._flush()
            self.structure.append(["meta", self._apply_typo(stripped)])
            self.last_line_blank = False
            return

        if self.multifora_mode:
            if _TROIKA_RE_RESERVE_SECTION.search(stripped):
                self._flush()
                self.structure.append(["battle", self._apply_typo(stripped)])
                self.after_theme = False
                self.last_line_blank = False
                return
            if _TROIKA_RE_RESERVE_THEME.search(stripped):
                self._flush()
                self.structure.append(["theme", self._apply_typo(stripped)])
                self.after_theme = True
                self.last_line_blank = False
                return
            m_mf = _TROIKA_RE_MULTIFORA_QUESTION.search(stripped)
            if m_mf:
                self._flush()
                self.structure.append(["number", m_mf.group(1)])
                self.current_field = "question"
                self.current_content = stripped[m_mf.end():].strip()
                self.after_theme = False
                self.last_line_blank = False
                return
            if _TROIKA_RE_NUMBERED_THEME.match(
                stripped
            ) and not self._should_continue_source_list(stripped):
                self._flush()
                self.structure.append(
                    ["theme", self._apply_typo(_normalize_troika_theme_text(stripped))]
                )
                self.after_theme = True
                self.last_line_blank = False
                return

        if _TROIKA_RE_FINAL.search(stripped):
            if self.current_field == "source" and self.current_content.strip():
                self.current_content += SEP + stripped
            else:
                self._flush()
                self.structure.append(["meta", self._apply_typo(stripped)])
            self.last_line_blank = False
            return

        if heading_level == 1:
            self._flush()
            self.structure.append(
                ["theme", self._apply_typo(_normalize_troika_theme_text(stripped))]
            )
            self.after_theme = True
            self.last_line_blank = False
            return

        if _TROIKA_RE_HOST_NOTE.search(stripped):
            if self.current_field == "question":
                super()._handle_line(stripped)
            else:
                self._flush()
                self.structure.append(["meta", self._apply_typo(stripped)])
            self.last_line_blank = False
            return

        super()._handle_line(stripped)
        self.last_line_blank = False

    def _dispatch_label(self, stripped, regex, field, append=False):
        m = regex.search(stripped)
        source_is_list_label = False
        if field == "source" and m:
            source_label = m.group(0).lower()
            source_is_list_label = "источники" in source_label or "(и)" in source_label
        if (
            field == "source"
            and m
            and m.start() == 0
            and not self._current_question_has_answer()
        ):
            content = regex.sub("", stripped, 1).strip()
            if content.startswith("["):
                self._flush()
                self.current_field = "answer"
                self.current_content = content
                self.source_list_mode = False
                return True

        matched = super()._dispatch_label(stripped, regex, field, append=append)
        if matched:
            self.source_list_mode = (
                field == "source"
                and self.current_field == "source"
                and (
                    source_is_list_label
                    or not self.current_content.strip()
                    or _TROIKA_RE_SOURCE_ITEM.search(self.current_content.strip())
                )
            )
        return matched

    def _current_question_has_answer(self):
        if self.current_field == "answer":
            return True
        for etype, _ in reversed(self.structure):
            if etype in self._STRUCTURAL_TYPES or etype == "number":
                return False
            if etype == "answer":
                return True
        return False

    def _should_continue_source_list(self, stripped):
        if self.current_field != "source":
            return False
        if not self.current_content.strip():
            if not self.source_list_mode:
                return False
            source_item = _TROIKA_RE_SOURCE_ITEM.sub("", stripped, count=1).strip()
            return bool(self._RE_URL_LIKE.search(source_item))
        if not self.source_list_mode:
            return False
        if not self.last_line_blank:
            return True
        current_item = _TROIKA_RE_SOURCE_ITEM.search(stripped)
        source_item = _TROIKA_RE_SOURCE_ITEM.sub("", stripped, count=1).strip()
        if self._RE_URL_LIKE.search(source_item):
            return True
        if current_item:
            prev_items = list(
                re.finditer(
                    r"(?m)^\s*(\d+)[\.\)]\s+(.+)$", self.current_content
                )
            )
            if (
                prev_items
                and int(current_item.group(1)) == int(prev_items[-1].group(1)) + 1
                and not self._RE_URL_LIKE.search(prev_items[-1].group(2))
            ):
                return True
        return False

    def _dispatch_question_num(self, stripped):
        m = _TROIKA_RE_QUESTION_NUM.search(stripped)
        if not m:
            return False
        num = int(m.group(1))
        if num not in _TROIKA_QUESTION_NUMBERS:
            return False
        if self._should_continue_source_list(stripped):
            return False
        self._flush()
        self.structure.append(["number", str(num)])
        question_text = stripped[m.end():].strip()
        if question_text:
            self.current_field = "question"
            self.current_content = question_text
        return True

    def _dispatch_question_num_only(self, stripped):
        m = _TROIKA_RE_QUESTION_NUM_ONLY.search(stripped)
        if not m:
            return False
        num = int(m.group(1))
        if num not in _TROIKA_QUESTION_NUMBERS:
            return False
        if self._should_continue_source_list(stripped):
            return False
        self._flush()
        self.structure.append(["number", str(num)])
        self.current_field = "question"
        self.current_content = ""
        return True


def troika_parse_text(text, args=None, logger=None):
    """Parse Troika plain text into a battle/theme/question structure."""
    return TroikaParser(args=args, logger=logger).parse(text)


def docx_to_text(docxfile, args=None, logger=None, inject_heading_markers=False):
    """Convert a DOCX file to plain text preserving images, lists, and optional heading markers.

    When ``inject_heading_markers`` is True, ``h1``/``h2``/``h3`` tags are prefixed with
    ``$$H1$$``/``$$H2$$``/``$$H3$$`` so downstream parsers can detect headings.
    """
    logger = logger or DummyLogger()
    args = args or DefaultNamespace()
    for_ol = {}
    preserve_ol_start = getattr(args, "game", None) in ("si", "troika")

    def get_number(tag):
        if tag not in for_ol:
            if not preserve_ol_start:
                for_ol[tag] = 1
            else:
                try:
                    for_ol[tag] = int(tag.get("start", 1))
                except (TypeError, ValueError):
                    for_ol[tag] = 1
        else:
            for_ol[tag] += 1
        return for_ol[tag]

    target_dir = os.path.dirname(os.path.abspath(docxfile))
    no_image_prefix = getattr(args, "no_image_prefix", False) or getattr(
        args, "not_image_prefix", False
    )
    if not no_image_prefix:
        bn_for_img = (
            os.path.splitext(os.path.basename(docxfile))[0].replace(" ", "_") + "_"
        )
    else:
        bn_for_img = ""
    parsing_engine = getattr(args, "parsing_engine", "python_docx") or "python_docx"
    temp_dir = None
    if parsing_engine == "python_docx":
        txt = python_docx_to_text(
            docxfile,
            args,
            target_dir,
            bn_for_img,
            inject_heading_markers,
            preserve_ol_start,
            logger,
        )
        imgpaths = []
    elif parsing_engine == "pypandoc":
        txt = _pypandoc_convert_file(docxfile, "plain", extra_args=["--wrap=none"])
        txt = escape_underscores_except_urls(txt, skip_escaped=True)
        imgpaths = []
    else:
        if parsing_engine == "pypandoc_html":
            temp_dir = tempfile.mkdtemp()
            html = _pypandoc_convert_file(
                docxfile,
                "html",
                extra_args=["--wrap=none", f"--extract-media={temp_dir}"],
            )
        else:
            with open(docxfile, "rb") as docx_file:
                html = mammoth.convert_to_html(docx_file).value
        if args.debug:
            with open(
                os.path.join(target_dir, "debugdebug.pydocx"), "w", encoding="utf-8"
            ) as dbg:
                dbg.write(html)
        input_docx = (
            html.replace("</strong><strong>", "")
            .replace("</em><em>", "")
        )
        bsoup = BeautifulSoup(input_docx, "html.parser")

        if args.debug:
            with open(
                os.path.join(target_dir, "debug.pydocx"), "w", encoding="utf-8"
            ) as dbg:
                dbg.write(input_docx)

        normalize_html_before_flattening(bsoup)

        for tag in bsoup.find_all("style"):
            tag.extract()
        for br in bsoup.find_all("br"):
            br.replace_with("\n")
        imgpaths = []
        for tag in bsoup.find_all("img"):
            if parsing_engine == "pypandoc_html":
                src = tag["src"]
                _, ext = os.path.splitext(src)
                if ext.lower() in (".jpg", ".jpeg"):
                    ext = ".jpeg"
                imgname = generate_imgname(target_dir, ext[1:], prefix=bn_for_img)
                shutil.copy(src, os.path.join(target_dir, imgname))
                imgpath = os.path.basename(imgname)
            else:
                imgparse = parse("data:image/{ext};base64,{b64}", tag["src"])
                if imgparse:
                    imgname = generate_imgname(
                        target_dir, imgparse["ext"], prefix=bn_for_img
                    )
                    with open(os.path.join(target_dir, imgname), "wb") as f:
                        f.write(base64.b64decode(imgparse["b64"]))
                    imgpath = os.path.basename(imgname)
                else:
                    imgpath = "BROKEN_IMAGE"
            tag.insert_before(f"IMGPATH({len(imgpaths)})")
            imgpath_formatted = f"(img {imgpath})"
            imgpaths.append(imgpath_formatted)
            tag.extract()
        for node in bsoup.find_all(string=True):
            if node.parent and node.parent.name in ("script", "style"):
                continue
            escaped = escape_underscores_except_urls(str(node))
            if escaped != node:
                node.replace_with(escaped)
        for tag in bsoup.find_all("p"):
            ensure_line_breaks(tag)

        preserve_formatting = getattr(args, "preserve_formatting", False)
        for tag in bsoup.find_all("b"):
            if preserve_formatting:
                tag.insert(0, "__")
                tag.append("__")
            tag.unwrap()
        for tag in bsoup.find_all("strong"):
            if preserve_formatting:
                tag.insert(0, "__")
                tag.append("__")
            tag.unwrap()
        for tag in bsoup.find_all("i"):
            if preserve_formatting:
                tag.insert(0, "_")
                tag.append("_")
            tag.unwrap()
        for tag in bsoup.find_all("em"):
            if preserve_formatting:
                tag.insert(0, "_")
                tag.append("_")
            tag.unwrap()
        if getattr(args, "fix_spans", False):
            for tag in bsoup.find_all("span"):
                tag.unwrap()
        heading_markers = (
            {"h1": "$$H1$$ ", "h2": "$$H2$$ ", "h3": "$$H3$$ "}
            if inject_heading_markers
            else {}
        )
        for h in ["h1", "h2", "h3", "h4"]:
            for tag in bsoup.find_all(h):
                marker = heading_markers.get(h)
                if marker:
                    tag.insert(0, marker)
                ensure_line_breaks(tag)
        to_append = []
        for tag in bsoup.find_all("li"):
            if tag.parent and tag.parent.name == "ol":
                num = get_number(tag.parent)
                to_append.append((tag, f"{num}. "))
        for tag, prefix in to_append:
            tag.insert(0, prefix)
            ensure_line_breaks(tag)
        for tag in bsoup.find_all("table"):
            try:
                table = html2md(str(tag))
                tag.insert_before(table)
            except (TypeError, ValueError):
                logger.error(f"couldn't parse html table: {tag!s}")
            tag.extract()
        for tag in bsoup.find_all("hr"):
            tag.extract()
        links = getattr(args, "links", "unwrap") or "unwrap"
        if links == "unwrap":
            for tag in bsoup.find_all("a"):
                if tag.get_text().startswith("http"):
                    tag.unwrap()
                elif (
                    tag.get("href")
                    and tag["href"].startswith("http")
                    and tag.get_text().strip() not in tag["href"]
                    and (
                        urllib.parse.unquote(tag.get_text().strip())
                        not in urllib.parse.unquote(tag["href"])
                    )
                ):
                    tag.string = f"{tag.get_text()} ({tag['href']})"
                    tag.unwrap()
        elif links == "old":
            for tag in bsoup.find_all("a"):
                if not tag.string or rew(tag.string) == "":
                    tag.extract()
                else:
                    tag.string = tag["href"]
                    tag.unwrap()

        if args.debug:
            with open(
                os.path.join(target_dir, "debug_raw.html"), "w", encoding="utf-8"
            ) as dbg:
                dbg.write(str(bsoup))
            with open(
                os.path.join(target_dir, "debug.html"), "w", encoding="utf-8"
            ) as dbg:
                dbg.write(bsoup.prettify())

        if parsing_engine == "mammoth_hard_unwrap":
            for tag in bsoup:
                if isinstance(tag, bs4.element.Tag):
                    tag.unwrap()
            txt = bsoup.prettify()
        else:
            found = True
            while found:
                found = False
                for tag in bsoup:
                    if isinstance(tag, bs4.element.Tag):
                        tag.unwrap()
                        found = True
            txt = str(bsoup)
    if temp_dir is not None:
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
        .replace("&amp;", "&")
    )
    txt = re.sub(r"_ +_", "", txt)  # fix bad italic from Word
    for i, elem in enumerate(imgpaths):
        txt = txt.replace(f"IMGPATH({i})", elem)

    return normalize_docx_spacing(txt)


def chgk_parse_docx(docxfile, defaultauthor="", args=None, logger=None):
    logger = logger or DummyLogger()
    args = args or DefaultNamespace()
    target_dir = os.path.dirname(os.path.abspath(docxfile))

    txt = docx_to_text(docxfile, args=args, logger=logger, inject_heading_markers=False)

    if args.debug:
        with open(
            os.path.join(target_dir, "debug.debug"), "w", encoding="utf-8"
        ) as dbg:
            dbg.write(txt)

    final_structure = chgk_parse(txt, defaultauthor=defaultauthor, args=args)
    return final_structure


def si_parse_docx(docxfile, args=None, logger=None):
    """Parse an SI (Своя Игра) DOCX file into a 4s structure."""
    logger = logger or DummyLogger()
    args = args or DefaultNamespace()
    target_dir = os.path.dirname(os.path.abspath(docxfile))

    txt = docx_to_text(docxfile, args=args, logger=logger, inject_heading_markers=True)

    if getattr(args, "debug", False):
        with open(
            os.path.join(target_dir, "si_debug.txt"), "w", encoding="utf-8"
        ) as dbg:
            dbg.write(txt)

    return si_parse_text(txt, args=args, logger=logger)


def troika_parse_docx(docxfile, args=None, logger=None):
    """Parse a Troika DOCX file into a 4s-family structure."""
    logger = logger or DummyLogger()
    args = args or DefaultNamespace()
    target_dir = os.path.dirname(os.path.abspath(docxfile))

    txt = docx_to_text(docxfile, args=args, logger=logger, inject_heading_markers=True)

    if getattr(args, "debug", False):
        with open(
            os.path.join(target_dir, "troika_debug.txt"), "w", encoding="utf-8"
        ) as dbg:
            dbg.write(txt)

    return troika_parse_text(txt, args=args, logger=logger)


def parse_wrapper(path, args, logger=None):
    abspath = os.path.abspath(path)
    target_dir = os.path.dirname(abspath)
    logger = logger or init_logger("parser")
    game = getattr(args, "game", None)
    ext_in = os.path.splitext(abspath)[1]

    if game in ("si", "troika"):
        # SI questions are point values, and Troika numbers repeat in each theme;
        # always preserve explicit numbering for both formats.
        if (
            not getattr(args, "numbers_handling", None)
            or args.numbers_handling == "default"
        ):
            args.numbers_handling = "all"
        if ext_in == ".docx":
            if game == "si":
                final_structure = si_parse_docx(abspath, args=args, logger=logger)
            else:
                final_structure = troika_parse_docx(
                    abspath, args=args, logger=logger
                )
        elif ext_in == ".txt":
            from chgksuite.common import read_text_file

            text = read_text_file(abspath)
            if game == "si":
                final_structure = si_parse_text(text, args=args, logger=logger)
            else:
                final_structure = troika_parse_text(text, args=args, logger=logger)
        else:
            sys.stderr.write("Error: unsupported file format." + SEP)
            sys.exit()
    else:
        if args.defaultauthor == "off":
            defaultauthor = ""
        elif args.defaultauthor == "file":
            defaultauthor = os.path.splitext(os.path.basename(abspath))[0]
        else:
            defaultauthor = args.defaultauthor
        if ext_in == ".txt":
            final_structure = chgk_parse_txt(
                abspath,
                defaultauthor=defaultauthor,
                encoding=args.encoding,
                args=args,
                logger=logger,
            )
        elif ext_in == ".docx":
            final_structure = chgk_parse_docx(
                abspath, defaultauthor=defaultauthor, args=args, logger=logger
            )
        else:
            sys.stderr.write("Error: unsupported file format." + SEP)
            sys.exit()

    ext = game_to_ext(game)
    outfilename = os.path.join(target_dir, make_filename(abspath, ext, args))
    logger.info(f"Output: {os.path.abspath(outfilename)}")
    with open(outfilename, "w", encoding="utf-8") as output_file:
        output_file.write(compose_4s(final_structure, args=args))
    return outfilename


def gui_parse(args):
    logger = init_logger("parser", debug=args.debug)

    ld = get_lastdir()
    if args.parsedir:
        if os.path.isdir(args.filename):
            ld = args.filename
            set_lastdir(ld)
            ext = game_to_ext(getattr(args, "game", None))
            for filename in os.listdir(args.filename):
                if filename.endswith((".docx", ".txt")) and not os.path.isfile(
                    os.path.join(args.filename, make_filename(filename, ext, args))
                ):
                    outfilename = parse_wrapper(
                        os.path.join(args.filename, filename),
                        args,
                        logger=logger,
                    )
                    logger.info(
                        f"{filename} -> {os.path.basename(outfilename)}"
                    )

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

        outfilename = parse_wrapper(args.filename, args, logger=logger)
        if outfilename and not args.console_mode:
            print(
                "Please review the resulting file {}:".format(
                    make_filename(
                        args.filename,
                        game_to_ext(getattr(args, "game", None)),
                        args,
                    )
                )
            )
            texteditor = load_settings().get("editor") or EDITORS[sys.platform]
            subprocess.call(shlex.split(f'{texteditor} "{outfilename}"'))
        if args.passthrough:
            cargs = DefaultNamespace()
            cargs.action = "compose"
            cargs.filename = outfilename
            gui_compose(cargs)
