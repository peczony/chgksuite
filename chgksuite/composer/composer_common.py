import base64
import contextlib
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import time
import urllib.parse

import requests
import toml
from PIL import Image

import chgksuite.typotools as typotools
from chgksuite.common import DummyLogger, get_chgksuite_dir, init_logger, log_wrap
from chgksuite.typotools import re_lowercase, re_percent, re_uppercase, re_url


def md5(s):
    return hashlib.md5(s).hexdigest()


IMGUR_CLIENT_ID = "e86275b3316c6d6"


def backtick_replace(el):
    while "`" in el:
        if el.index("`") + 1 >= len(el):
            el = el.replace("`", "")
        else:
            if el.index("`") + 2 < len(el) and re.search(r"\s", el[el.index("`") + 2]):
                el = el[: el.index("`") + 2] + "" + el[el.index("`") + 2 :]
            if el.index("`") + 1 < len(el) and re_lowercase.search(
                el[el.index("`") + 1]
            ):
                el = (
                    el[: el.index("`") + 1]
                    + ""
                    + el[el.index("`") + 1]
                    + "\u0301"
                    + el[el.index("`") + 2 :]
                )
            elif el.index("`") + 1 < len(el) and re_uppercase.search(
                el[el.index("`") + 1]
            ):
                el = (
                    el[: el.index("`") + 1]
                    + ""
                    + el[el.index("`") + 1]
                    + "\u0301"
                    + el[el.index("`") + 2 :]
                )
            el = el[: el.index("`")] + el[el.index("`") + 1 :]
    return el


def remove_accents_standalone(s, labels):
    hs = labels["question_labels"]["handout_short"]
    re_hs = re.compile(f"\\[{hs}(.+?)\\]", flags=re.DOTALL)
    replacements = {}
    n_handouts = 0
    while match := re_hs.search(s):
        original = match.group(0)
        n_handouts += 1
        replacements[original] = f"HANDOUT_{str(n_handouts).zfill(3)}"
        s = s.replace(original, replacements[original])
    s = s.replace("\u0301", "")
    for k, v in replacements.items():
        s = s.replace(v, k)
    return s


def unquote(bytestring):
    return urllib.parse.unquote(bytestring.decode("utf8")).encode("utf8")


def make_filename(s, ext, args, addsuffix=""):
    bn = os.path.splitext(os.path.basename(s))[0]
    if addsuffix:
        bn += addsuffix
    if args.add_ts == "on":
        return "{}_{}.{}".format(
            bn, datetime.datetime.now().strftime("%Y%m%dT%H%M"), ext
        )
    return bn + "." + ext


@contextlib.contextmanager
def make_temp_directory(**kwargs):
    temp_dir = tempfile.mkdtemp(**kwargs)
    yield temp_dir
    shutil.rmtree(temp_dir)


def proportional_resize(tup):
    if max(tup) > 600:
        return tuple([int(x * 600 / max(tup)) for x in tup])
    if max(tup) < 200:
        return tuple([int(x * 200 / max(tup)) for x in tup])
    return tup


def imgsize(imgfile):
    img = Image.open(imgfile)
    width, height = proportional_resize((img.width, img.height))
    return width, height


def convert_size(width, height, dimensions="pixels", emsize=25, dpi=120):
    if dimensions == "pixels":
        return width, height
    if dimensions == "ems":
        return width / emsize, height / emsize
    if dimensions == "inches":
        return width / dpi, height / dpi


def search_for_imgfile(imgfile, tmp_dir, targetdir):
    if os.path.isfile(imgfile):
        return imgfile
    for dirname in [tmp_dir, targetdir]:
        if not os.path.isdir(dirname):
            continue
        imgfile2 = os.path.join(dirname, os.path.basename(imgfile))
        if os.path.isfile(imgfile2):
            return imgfile2
    raise Exception("Image file {} not found\n".format(imgfile))


def parse_single_size(ssize, dpi=120, emsize=25):
    if ssize.endswith("in"):
        ssize = ssize[:-2]
        return float(ssize) * dpi
    if ssize.endswith("em"):
        ssize = ssize[:-2]
        return float(ssize) * emsize
    if ssize.endswith("px"):
        ssize = ssize[:-2]
    return float(ssize)


def parseimg(s, dimensions="pixels", tmp_dir=None, targetdir=None):
    width = -1
    height = -1
    sp = shlex.split(s)
    imgfile = sp[-1]
    imgfile = search_for_imgfile(imgfile, tmp_dir, targetdir)
    size = imgsize(imgfile)
    big, inline = False, False
    if "big" in sp:
        big = True
        sp = [x for x in sp if x != "big"]

    if "inline" in sp:
        inline = True
        sp = [x for x in sp if x != "inline"]

    if len(sp) == 1:
        width, height = convert_size(*size, dimensions=dimensions)
    else:
        for spsp in sp[:-1]:
            spspsp = spsp.split("=")
            if spspsp[0] == "w":
                width = parse_single_size(spspsp[1])
            if spspsp[0] == "h":
                height = parse_single_size(spspsp[1])
        if width != -1 and height == -1:
            height = size[1] * (width / size[0])
        elif width == -1 and height != -1:
            width = size[0] * (height / size[1])
        width, height = convert_size(width, height, dimensions=dimensions)
    return {
        "imgfile": imgfile.replace("\\", "/"),
        "width": width,
        "height": height,
        "big": big,
        "inline": inline,
    }


class Imgur:
    def __init__(self, client_id):
        self.client_id = client_id
        self.cache_file_path = os.path.join(get_chgksuite_dir(), "image_cache.json")
        if os.path.isfile(self.cache_file_path):
            try:
                with open(self.cache_file_path) as f:
                    self.cache = json.load(f)
            except json.decoder.JSONDecodeError:
                self.cache = {}
        else:
            self.cache = {}

    def upload_image(self, path, title=None):
        with open(path, "rb") as image_file:
            binary_data = image_file.read()
        image_bytes = base64.b64encode(binary_data)
        image = image_bytes.decode("utf8", errors="replace")
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        if sha256 in self.cache:
            return {"data": {"link": self.cache[sha256]}}
        payload = {
            "album_id": None,
            "image": image,
            "title": title,
            "description": None,
        }
        retries = 0
        req = None
        while (not req or req.status_code != 200) and retries < 10:
            req = requests.post(
                "https://api.imgur.com/3/image",
                json=payload,
                headers={"Authorization": f"Client-ID {self.client_id}"},
            )
            if req.status_code != 200:
                sys.stderr.write(f"got 403 from imgur, retry {retries + 1}...")
                retries += 1
                time.sleep(5)
        try:
            assert req.status_code == 200
            json_ = req.json()
            self.cache[sha256] = json_["data"]["link"]
            with open(self.cache_file_path, "w", encoding="utf8") as f:
                json.dump(self.cache, f, indent=2, sort_keys=True)
            return json_
        except Exception as e:
            raise Exception(
                f"Imgur API error code {req.status_code}: "
                f"{req.content.decode('utf8', errors='replace')}, raw exception data: "
                f"{type(e)} {e}"
            )


def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0] + indices, indices + [None])]


def starts_either(s, i, variants):
    for v in variants:
        if s[i : i + len(v)] == v:
            return True
    return False


def find_next_unescaped(ss, index, length=1):
    j = index + length
    while j < len(ss):
        if ss[j] == "\\" and j + 2 < len(ss):
            j += 2
        if ss[j : j + length] == ss[index : index + length]:
            return j
        j += 1
    return -1


def _parse_4s_elem(s, logger=None):
    logger = logger or DummyLogger()

    s = s.replace("\\_", "$$$$UNDERSCORE$$$$")
    s = s.replace("\\~", "$$$$TILDE$$$$")
    for gr in re_url.finditer(s):
        gr0 = gr.group(0)
        s = s.replace(gr0, gr0.replace("_", "$$$$UNDERSCORE$$$$"))
        s = s.replace(gr0, gr0.replace("~", "$$$$TILDE$$$$"))

    grs = sorted(
        [match.group(0) for match in re_percent.finditer(s)], key=len, reverse=True
    )
    for gr in grs:
        try:
            s = s.replace(gr, unquote(gr.encode("utf8")).decode("utf8"))
        except Exception as e:
            logger.debug(f"error decoding on line {log_wrap(gr)}: {type(e)} {e}\n")

    i = 0
    topart = []
    while i < len(s):
        if s[i] in ("_", "~"):
            logger.debug("found {} at {} of line {}".format(s[i], i, s))
            j = i + 1
            while s[j] == s[i]:
                j += 1
            length = j - i
            topart.append(i)
            if find_next_unescaped(s, i, length) != -1:
                topart.append(find_next_unescaped(s, i, length) + length)
                i = find_next_unescaped(s, i, length) + length + 1
                continue
        if (
            s[i] == "("
            and i + len("(img") < len(s)
            and "".join(s[i : i + len("(img")]) == "(img"
        ):
            topart.append(i)
            if typotools.find_matching_closing_bracket(s, i) is not None:
                topart.append(typotools.find_matching_closing_bracket(s, i) + 1)
                i = typotools.find_matching_closing_bracket(s, i)
        if (
            s[i] == "("
            and i + len("(screen") < len(s)
            and "".join(s[i : i + len("(screen")]) == "(screen"
        ):
            topart.append(i)
            if typotools.find_matching_closing_bracket(s, i) is not None:
                topart.append(typotools.find_matching_closing_bracket(s, i) + 1)
                i = typotools.find_matching_closing_bracket(s, i)
        if s[i : i + len("(PAGEBREAK)")] == "(PAGEBREAK)":
            topart.append(i)
            topart.append(i + len("(PAGEBREAK)"))
        if s[i : i + len("(LINEBREAK)")] == "(LINEBREAK)":
            topart.append(i)
            topart.append(i + len("(LINEBREAK)"))
        if starts_either(s, i, ("http://", "https://")):
            topart.append(i)
            j = i + 1
            bracket_level = 0
            while j < len(s) and not (
                s[j].isspace() or s[j] == ")" and bracket_level == 0
            ):
                if s[j] == "(":
                    bracket_level += 1
                elif s[j] == ")" and bracket_level > 0:
                    bracket_level -= 1
                j += 1
            if s[j - 1] in (",", ".", ";"):
                topart.append(j - 1)
            else:
                topart.append(j)
            i = j
        i += 1

    topart = sorted(topart)

    parts = [["", "".join(x.replace("\u6565", ""))] for x in partition(s, topart)]

    def _process(s):
        s = s.replace("\\_", "_")
        s = s.replace("\\.", ".")
        s = s.replace("$$$$UNDERSCORE$$$$", "_")
        s = s.replace("$$$$TILDE$$$$", "~")
        return s

    for part in parts:
        if not part[1]:
            continue
        try:
            if part[1].startswith("_") and part[1].endswith("_"):
                j = 1
                while j < len(part[1]) and part[1][j] == "_" and part[1][-j - 1] == "_":
                    j += 1
                part[1] = part[1][j:-j]
                if j == 1:
                    part[0] = "italic"
                elif j == 2:
                    part[0] = "bold"
                elif j == 3:
                    part[0] = "underline"
                elif j == 4:
                    part[0] = "italicbold"
                elif j == 5:
                    part[0] = "boldunderline"
                elif j >= 6:
                    part[0] = "italicboldunderline"
            if part[1].startswith("~") and part[1].endswith("~"):
                part[0] = "strike"
                part[1] = part[1][1:-1]
            if part[1] == "(PAGEBREAK)":
                part[0] = "pagebreak"
                part[1] = ""
            if part[1] == "(LINEBREAK)":
                part[0] = "linebreak"
                part[1] = ""
            if len(part[1]) > 4 and part[1][:4] == "(img":
                if part[1][-1] != ")":
                    part[1] = part[1] + ")"
                part[1] = part[1][4:-1]
                part[0] = "img"
                logger.debug("found img at {}".format(part[1]))
            if len(part[1]) > 7 and part[1][:7] == "(screen":
                if part[1][-1] != ")":
                    part[1] = part[1] + ")"
                for_print, for_screen = part[1][8:-1].split("|")
                for_print = _process(for_print)
                for_screen = _process(for_screen)
                part[1] = {"for_print": for_print, "for_screen": for_screen}
                part[0] = "screen"
                continue
            if part[1].startswith(("http://", "https://")):
                part[0] = "hyperlink"
            if len(part[1]) > 3 and part[1][:4] == "(sc":
                if part[1][-1] != ")":
                    part[1] = part[1] + ")"
                part[1] = part[1][3:-1]
                part[0] = "sc"
                logger.debug("found img at {}".format(log_wrap(part[1])))
            part[1] = _process(part[1])
        except Exception as e:
            sys.stderr.write(f"Error on part {log_wrap(part)}: {type(e)} {e}\n")

    return parts


class BaseExporter:
    def __init__(self, *args, **kwargs):
        self.structure = args[0]
        self.args = args[1]
        self.dir_kwargs = args[2]
        with open(self.args.labels_file, encoding="utf8") as f:
            self.labels = toml.load(f)
        logger = kwargs.get("logger")
        if logger:
            self.logger = logger
        else:
            self.logger = init_logger("composer", debug=self.args.debug)

    def _replace_no_break(self, s):
        return typotools.replace_no_break(
            s,
            spaces=self.args.replace_no_break_spaces == "on",
            hyphens=self.args.replace_no_break_hyphens == "on",
        )

    def parse_4s_elem(self, *args, **kwargs):
        kwargs["logger"] = self.logger
        return _parse_4s_elem(*args, **kwargs)

    def get_label(self, question, field, number=None):
        if field == "question" and self.args.only_question_number:
            return str(question.get("number") or number)
        if field in ("question", "tour"):
            lbl = (question.get("overrides") or {}).get(field) or self.labels[
                "question_labels"
            ][field]
            num = question.get("number") or number
            if self.args.language in ("uz", "uz_cyr"):
                return f"{num} – {lbl}"
            elif self.args.language == "kz":
                return f"{num}-{lbl}"
            else:
                return f"{lbl} {num}"
        if field in (question.get("overrides") or {}):
            return question["overrides"][field]
        if field == "source" and isinstance(question.get("source" or ""), list):
            return self.labels["question_labels"]["sources"]
        return self.labels["question_labels"][field]

    def remove_square_brackets(self, s):
        hs = self.labels["question_labels"]["handout_short"]
        s = s.replace("\\[", "LEFTSQUAREBRACKET")
        s = s.replace("\\]", "RIGHTSQUAREBRACKET")
        s = re.sub(f"\\[{hs}(.+?)\\]", "{" + hs + "\\1}", s, flags=re.DOTALL)
        i = 0
        while "[" in s and "]" in s and i < 10:
            s = re.sub(" *\\[.+?\\]", "", s, flags=re.DOTALL)
            s = s.strip()
            i += 1
        if i == 10:
            sys.stderr.write(
                f"Error replacing square brackets on question: {s}, retries exceeded\n"
            )
        s = re.sub("\\{" + hs + "(.+?)\\}", "[" + hs + "\\1]", s, flags=re.DOTALL)
        s = s.replace("LEFTSQUAREBRACKET", "[")
        s = s.replace("RIGHTSQUAREBRACKET", "]")
        return s
