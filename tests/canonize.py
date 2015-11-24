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

def main():
    for filename in os.listdir(currentdir):
        if filename.endswith(('.docx', '.txt')):
            print('Canonizing {}...'.format(filename))
            parsed = chgk_parse(filename)
            with codecs.open(
                os.path.basename(filename)+'.canon','w','utf8') as f:
                f.write(compose_4s(parsed))


if __name__ == "__main__":
    main()