#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import os
import argparse
import codecs
import inspect
import json

ALLOWED_IMAGES = ["long_handout.png", "test.jpg"]

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)

with open(os.path.join(currentdir, "settings.json")) as f:
    settings = json.loads(f.read())

from chgksuite.parser import chgk_parse_txt, chgk_parse_docx, compose_4s  # noqa: E402


from chgksuite_test import DefaultArgs  # noqa: E402


def workaround_chgk_parse(filename, **kwargs):
    if filename.endswith(".txt"):
        return chgk_parse_txt(filename, args=DefaultArgs(**kwargs))
    elif filename.endswith(".docx"):
        return chgk_parse_docx(filename, args=DefaultArgs(**kwargs))
    return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parsing_engine", default="mammoth")
    args = parser.parse_args()

    for filename in os.listdir(currentdir):
        if filename.endswith((".docx", ".txt")):
            print("Canonizing {}...".format(filename))
            if filename in settings and settings[filename].get("function_args"):
                function_args = settings[filename].get("function_args")
            else:
                function_args = {}
            parsed = workaround_chgk_parse(
                os.path.join(currentdir, filename),
                parsing_engine=args.parsing_engine,
                **function_args,
            )
            for filename1 in os.listdir(currentdir):
                if (
                    filename1.endswith((".jpg", ".jpeg", ".png", ".gif"))
                    and not filename1.startswith("ALLOWED")
                    and filename1 not in ALLOWED_IMAGES
                ):
                    os.remove(os.path.join(currentdir, filename1))
            with codecs.open(
                os.path.join(currentdir, filename) + ".canon", "w", "utf8"
            ) as f:
                f.write(compose_4s(parsed, args=DefaultArgs()))


if __name__ == "__main__":
    main()
