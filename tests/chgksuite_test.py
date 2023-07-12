#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import codecs
import os
import sys
import inspect
import tempfile
import shutil
import contextlib
import subprocess
import pytest

from chgksuite.parser import (
    chgk_parse_txt,
    chgk_parse_docx,
    compose_4s,
)
from chgksuite.common import DefaultArgs
from chgksuite.typotools import get_quotes_right

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)


ljlogin, ljpassword = open(os.path.join(currentdir, "ljcredentials")).read().split("\t")


def workaround_chgk_parse(filename, **kwargs):
    if filename.endswith(".txt"):
        return chgk_parse_txt(filename)
    elif filename.endswith(".docx"):
        return chgk_parse_docx(filename, args=DefaultArgs(**kwargs))
    return


QUOTE_TEST_CASES = [
    ('«"Альфа" Бета»', "«„Альфа“ Бета»"),
    ("«“Альфа” Бета»", "«„Альфа“ Бета»"),
    ("«„Альфа“ Бета»", "«„Альфа“ Бета»"),
    ("«Альфа», “Бета”", "«Альфа», «Бета»"),
    (
        '"Он сказал: "Привет!". А потом заплакал"',
        "«Он сказал: „Привет!“. А потом заплакал»",
    ),
    (
        "“Он сказал: “Привет!”. А потом заплакал”",
        "«Он сказал: „Привет!“. А потом заплакал»",
    ),
]


@pytest.mark.parametrize("a,expected", QUOTE_TEST_CASES)
def test_quotes(a, expected):
    assert get_quotes_right(a) == expected


@contextlib.contextmanager
def make_temp_directory(**kwargs):
    temp_dir = tempfile.mkdtemp(**kwargs)
    yield temp_dir
    shutil.rmtree(os.path.abspath(temp_dir))


def normalize(string):
    return string.replace("\r\n", "\n")


CANON_FILENAMES = [
    fn for fn in os.listdir(currentdir) if fn.endswith(".canon")
]

@pytest.mark.parametrize("filename", CANON_FILENAMES)
def test_canonical_equality(parsing_engine, filename):
    print(os.getcwd())
    with make_temp_directory(dir=".") as temp_dir:
        to_parse_fn = filename[:-6]
        print(os.getcwd())
        shutil.copy(os.path.join(currentdir, filename), temp_dir)
        print(os.getcwd())
        shutil.copy(os.path.join(currentdir, to_parse_fn), temp_dir)
        print(os.getcwd())
        print("Testing {}...".format(filename[:-6]))
        print(os.getcwd())
        bn, _ = os.path.splitext(to_parse_fn)
        call_args = [
            "python",
            "-m",
            "chgksuite",
            "parse",
            "--parsing_engine",
            parsing_engine,
            os.path.join(temp_dir, to_parse_fn),
        ]
        subprocess.call(call_args, timeout=5)
        with codecs.open(os.path.join(temp_dir, bn + ".4s"), "r", "utf8") as f:
            parsed = f.read()
        with codecs.open(os.path.join(temp_dir, filename), "r", "utf8") as f:
            canonical = f.read()
        assert normalize(canonical) == normalize(parsed)

TO_DOCX_FILENAMES = [
    fn for fn in os.listdir(currentdir) if fn.endswith((".docx", ".txt"))
]
TO_DOCX_FILENAMES.remove("balt09-1.txt")  # TODO: rm this line once dns is fixed

@pytest.mark.parametrize("filename", TO_DOCX_FILENAMES)
def test_docx_composition(filename):
    print("Testing {}...".format(filename))
    with make_temp_directory(dir=".") as temp_dir:
        shutil.copy(os.path.join(currentdir, filename), temp_dir)
        temp_dir_filename = os.path.join(temp_dir, filename)
        parsed = workaround_chgk_parse(temp_dir_filename)
        file4s = os.path.splitext(filename)[0] + ".4s"
        composed_abspath = os.path.join(temp_dir, file4s)
        print(composed_abspath)
        with codecs.open(composed_abspath, "w", "utf8") as f:
            f.write(compose_4s(parsed, args=DefaultArgs()))
        call_args = [
            "python",
            "-m",
            "chgksuite",
            "compose",
            "docx",
            composed_abspath,
        ]
        code = subprocess.call(call_args, timeout=5)
        assert 0 == code


@pytest.mark.tex
def test_tex_composition():
    for filename in os.listdir(currentdir):
        if (
            filename.endswith((".docx", ".txt"))
            and filename == "Kubok_knyagini_Olgi-2015.docx"
        ):
            print("Testing {}...".format(filename))
            with make_temp_directory(dir=".") as temp_dir:
                shutil.copy(os.path.join(currentdir, filename), temp_dir)
                temp_dir_filename = os.path.join(temp_dir, filename)
                parsed = workaround_chgk_parse(temp_dir_filename)
                file4s = os.path.splitext(filename)[0] + ".4s"
                composed_abspath = os.path.join(temp_dir, file4s)
                print(composed_abspath)
                with codecs.open(composed_abspath, "w", "utf8") as f:
                    f.write(compose_4s(parsed, args=DefaultArgs()))
                code = subprocess.call(
                    [
                        "python",
                        "-m",
                        "chgksuite",
                        "compose",
                        "tex",
                        composed_abspath,
                    ]
                )
                assert 0 == code
