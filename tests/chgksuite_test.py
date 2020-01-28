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

currentdir = os.path.dirname(
    os.path.abspath(inspect.getfile(inspect.currentframe()))
)
parentdir = os.path.dirname(currentdir)
# sys.path.insert(0, parentdir)

from chgksuite.parser import (
    chgk_parse,
    chgk_parse_txt,
    chgk_parse_docx,
    compose_4s,
)
from chgksuite.composer import parse_4s


class DefaultArgs(object):
    links = "unwrap"
    fix_spans = False

    def __getattr__(self, attribute):
        try:
            return object.__getattr__(self, attribute)
        except AttributeError:
            return None


ljlogin, ljpassword = (
    open(os.path.join(currentdir, "ljcredentials")).read().split("\t")
)


def workaround_chgk_parse(filename):
    if filename.endswith(".txt"):
        return chgk_parse_txt(filename)
    elif filename.endswith(".docx"):
        return chgk_parse_docx(filename, args=DefaultArgs())
    return


# def test_parse_empty():
#     for elem in {'', ' ', ' \n ', '\ufeff'}:
#         chgk_parse(elem)
#         parse_4s(elem)


@contextlib.contextmanager
def make_temp_directory(**kwargs):
    temp_dir = tempfile.mkdtemp(**kwargs)
    yield temp_dir
    shutil.rmtree(os.path.abspath(temp_dir))


def normalize(string):
    return string.replace("\r\n", "\n")


def test_canonical_equality():
    for filename in os.listdir(currentdir):
        if filename.endswith(".canon"):
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
                parsed = workaround_chgk_parse(
                    os.path.join(temp_dir, to_parse_fn)
                )
                with codecs.open(
                    os.path.join(temp_dir, filename), "r", "utf8"
                ) as f:
                    canonical = f.read()
                assert normalize(canonical) == normalize(compose_4s(parsed))


def test_composition():
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
                    f.write(compose_4s(parsed))
                code = subprocess.call(
                    [
                        "python",
                        "-m",
                        "chgksuite",
                        "compose",
                        "docx",
                        composed_abspath,
                    ]
                )
                assert 0 == code
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
