#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import codecs
import csv
import itertools
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import openpyxl
import toml

QUESTION_LABELS = [
    "handout",
    "question",
    "answer",
    "zachet",
    "nezachet",
    "comment",
    "source",
    "author",
    "number",
    "setcounter",
]
SEP = os.linesep
try:
    ENC = sys.stdout.encoding or "utf8"
except AttributeError:
    ENC = "utf8"

lastdir = os.path.join(os.path.dirname(os.path.abspath("__file__")), "lastdir")


def init_logger(logger_name, debug=False):
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        source_dir, _ = get_source_dirs()
        log_path = os.path.join(source_dir, f"{logger_name}.log")
        fh = logging.FileHandler(log_path, encoding="utf8")
        fh.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        if debug:
            ch.setLevel(logging.DEBUG)
        else:
            ch.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s | %(message)s")
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


def get_chgksuite_dir():
    chgksuite_dir = os.path.join(os.path.expanduser("~"), ".chgksuite")
    if not os.path.isdir(chgksuite_dir):
        os.mkdir(chgksuite_dir)
    return chgksuite_dir


def load_settings():
    chgksuite_dir = get_chgksuite_dir()
    settings_file = os.path.join(chgksuite_dir, "settings.toml")
    if not os.path.isfile(settings_file):
        return {}
    return toml.loads(Path(settings_file).read_text("utf8"))


def get_source_dirs():
    if getattr(sys, "frozen", False):
        sourcedir = os.path.dirname(sys.executable)
        resourcedir = os.path.join(sourcedir, "resources")
    else:
        sourcedir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
        resourcedir = os.path.join(sourcedir, "resources")
    return sourcedir, resourcedir


class DefaultArgs:
    console_mode = True
    debug = False
    fix_spans = False
    labels_file = os.path.join(get_source_dirs()[1], "labels_ru.toml")
    language = "ru"
    links = "unwrap"
    numbers_handling = "default"
    parsing_engine = "mammoth"
    regexes = os.path.join(get_source_dirs()[1], "regexes_ru.json")
    single_number_line_handling = "smart"
    typography_accents = "on"
    typography_dashes = "on"
    typography_percent = "on"
    typography_quotes = "on"
    typography_whitespace = "on"

    def __getattr__(self, attribute):
        try:
            return object.__getattr__(self, attribute)
        except AttributeError:
            return None

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def set_lastdir(path):
    chgksuite_dir = get_chgksuite_dir()
    lastdir = os.path.join(chgksuite_dir, "lastdir")
    with codecs.open(lastdir, "w", "utf8") as f:
        f.write(path)


def get_lastdir():
    chgksuite_dir = get_chgksuite_dir()
    lastdir = os.path.join(chgksuite_dir, "lastdir")
    if os.path.isfile(lastdir):
        with codecs.open(lastdir, "r", "utf8") as f:
            return f.read().rstrip()
    return "."


def retry_wrapper_factory(logger):
    def retry_wrapper(func, args=None, kwargs=None, retries=3):
        cntr = 0
        ret = None
        if not args:
            args = []
        if not kwargs:
            kwargs = {}
        while not ret and cntr < retries:
            try:
                ret = func(*args, **kwargs)
            except Exception as e:
                logger.error(f"exception {type(e)} {e}")
                time.sleep(5)
                cntr += 1
        return ret

    return retry_wrapper


def ensure_utf8(s):
    if isinstance(s, bytes):
        return s.decode("utf8", errors="replace")
    return s


class DummyLogger(object):
    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class DefaultNamespace(argparse.Namespace):
    def __init__(self, *args, **kwargs):
        for ns in args:
            if isinstance(ns, argparse.Namespace):
                for name in vars(ns):
                    setattr(self, name, vars(ns)[name])
        else:
            for name in kwargs:
                setattr(self, name, kwargs[name])

    def __getattribute__(self, name):
        try:
            return argparse.Namespace.__getattribute__(self, name)
        except AttributeError:
            return


def log_wrap(s, pretty_print=True):
    try_to_unescape = True
    if pretty_print and isinstance(s, (dict, list)):
        s = json.dumps(s, indent=2, ensure_ascii=False, sort_keys=True)
        try_to_unescape = False
    s = format(s)
    if sys.version_info.major == 2 and try_to_unescape:
        try:
            s = s.decode("unicode_escape")
        except UnicodeEncodeError:
            pass
    return s.encode(ENC, errors="replace").decode(ENC)


def check_question(question, logger=None):
    warnings = []
    for el in {"question", "answer", "source", "author"}:
        if el not in question:
            warnings.append(el)
    if len(warnings) > 0:
        logger.warning(
            "WARNING: question {} lacks the following fields: {}{}".format(
                log_wrap(question), ", ".join(warnings), SEP
            )
        )


def remove_double_separators(s):
    return re.sub(r"({})+".format(SEP), SEP, s)


def tryint(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return


def xlsx_to_results(xlsx_file_path):
    wb = openpyxl.load_workbook(xlsx_file_path)
    sheet = wb.active
    first = True
    res_by_tour = defaultdict(lambda: defaultdict(list))
    tour_len = defaultdict(lambda: 0)
    for row in sheet.iter_rows(values_only=True):
        if not any(x for x in row):
            continue
        if first:
            assert row[1] == "Название"
            if row[3] == "Тур":
                table_type = "tour"
            elif row[3] in ("1", 1):
                table_type = "full"
            first = False
            continue
        team_id = row[0]
        if not tryint(team_id):
            continue
        team_name = row[1]
        if table_type == "tour":
            tour = row[3]
            results = [x for x in row[4:] if x is not None]
        else:
            tour = 1
            results = [x for x in row[3:] if x is not None]
        rlen = len(results)
        tour_len[tour] = max(tour_len[tour], rlen)
        res_by_tour[(team_id, team_name)][tour] = results
    results = []

    tours = sorted(tour_len)
    for team_tup in res_by_tour:
        team_id, team_name = team_tup
        mask = []
        for tour in tours:
            team_res = res_by_tour[team_tup].get(tour) or []
            if len(team_res) < tour_len[tour]:
                team_res += [0] * (tour_len[tour] - len(team_res))
            for element in team_res:
                if tryint(element) in (1, 0):
                    mask.append(str(element))
                else:
                    mask.append("0")
        results.append(
            {
                "team": {"id": team_id},
                "current": {"name": team_name},
                "mask": "".join(mask),
            }
        )
    return results


def custom_csv_to_results(csv_file_path, **kwargs):
    results = []
    with open(csv_file_path, encoding="utf8") as f:
        reader = csv.reader(f, **kwargs)
        for row in itertools.islice(reader, 1, None):
            val = {
                "team": {"id": tryint(row[0])},
                "current": {"name": row[1]},
                "mask": "".join(row[3:]),
            }
            results.append(val)
    return results


def replace_escaped(s):
    return s.replace("\\[", "[").replace("\\]", "]")


def compose_4s(structure, args=None):
    types_mapping = {
        "meta": "# ",
        "section": "## ",
        "tour": "## ",
        "tourrev": "## ",
        "editor": "#EDITOR ",
        "heading": "### ",
        "ljheading": "###LJ ",
        "date": "#DATE ",
        "question": "? ",
        "answer": "! ",
        "zachet": "= ",
        "nezachet": "!= ",
        "source": "^ ",
        "comment": "/ ",
        "author": "@ ",
        "handout": "> ",
        "Question": None,
    }

    def format_element(z):
        if isinstance(z, str):
            return remove_double_separators(z)
        elif isinstance(z, list):
            if isinstance(z[1], list):
                return (
                    remove_double_separators(z[0])
                    + SEP
                    + "- "
                    + ("{}- ".format(SEP)).join(
                        ([remove_double_separators(x) for x in z[1]])
                    )
                )
            else:
                return (
                    SEP
                    + "- "
                    + ("{}- ".format(SEP)).join(
                        [remove_double_separators(x) for x in z]
                    )
                )

    def is_zero(s):
        return str(s).startswith("0") or not tryint(s)

    result = ""
    first_number = True
    for element in structure:
        if element[0] in types_mapping and types_mapping[element[0]]:
            result += types_mapping[element[0]] + format_element(element[1]) + SEP + SEP
        elif element[0] == "Question":
            tmp = ""
            overrides = element[1].get("overrides") or {}
            if "number" in element[1]:
                if not args.numbers_handling or args.numbers_handling == "default":
                    if is_zero(element[1]["number"]):
                        tmp += "№ " + str(element[1]["number"]) + SEP
                    elif first_number and tryint(element[1]["number"]) > 1:
                        tmp += "№№ " + str(element[1]["number"]) + SEP
                elif args.numbers_handling == "all":
                    tmp += "№ " + str(element[1]["number"]) + SEP
                if not is_zero(element[1]["number"]):
                    first_number = False
            for label in QUESTION_LABELS:
                override_label = (
                    "" if label not in overrides else ("!!{} ".format(overrides[label]))
                )
                if label in element[1] and label in types_mapping:
                    tmp += (
                        types_mapping[label]
                        + override_label
                        + format_element(element[1][label])
                        + SEP
                    )
            tmp = re.sub(r"{}+".format(SEP), SEP, tmp)
            tmp = tmp.replace("\r\r", "\r")
            result += tmp + SEP
    return result
