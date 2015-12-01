#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import sys
import os
import codecs
import argparse
import inspect

currentdir = os.path.dirname(
    os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir)

from chgk_parser import chgk_parse, chgk_parse_txt, chgk_parse_docx, compose_4s
from chgk_composer import parse_4s

def workaround_chgk_parse(filename):
    if filename.endswith(b'.txt'):
        return chgk_parse_txt(filename)
    elif filename.endswith(b'.docx'):
        return chgk_parse_docx(filename)
    return

def main():
    for filename in os.listdir(currentdir):
        if filename.endswith((b'.docx', b'.txt')):
            print(b'Canonizing {}...'.format(filename))
            parsed = workaround_chgk_parse(os.path.join(currentdir, filename))
            for filename1 in os.listdir(currentdir):
                if (filename1.endswith((b'.jpg', b'.jpeg', b'.png', b'.gif'))
                    and not filename1.startswith(b'ALLOWED')):
                    os.remove(os.path.join(currentdir, filename1))
            with codecs.open(
                os.path.join(currentdir, filename)+b'.canon','w','utf8') as f:
                f.write(compose_4s(parsed))


if __name__ == "__main__":
    main()