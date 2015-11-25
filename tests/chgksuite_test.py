#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import codecs
import os
import sys
import inspect

currentdir = os.path.dirname(
    os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir)

from chgk_parser import chgk_parse, chgk_parse_txt, chgk_parse_docx, compose_4s
from chgk_composer import parse_4s

def workaround_chgk_parse(filename):
    if filename.endswith('.txt'):
        return chgk_parse_txt(filename)
    elif filename.endswith('.docx'):
        return chgk_parse_docx(filename)
    return

# def test_identity():
#     for doc_ in os.listdir(currentdir):
#         parsed = ''
#         print doc_
#         print currentdir
#         doc = os.path.join(currentdir, doc_)
#         print os.path.abspath(doc)
#         if doc.endswith(('.txt', '.docx')):
#             assert os.path.isfile(doc)
#             if doc.endswith('.txt'):
#                 parsed = chgk_parse_txt(doc)
#             elif doc.endswith('.docx'):
#                 parsed = chgk_parse_docx(doc)
#             assert parse_4s(compose_4s(parsed)) == parsed

# def test_parse_empty():
#     for elem in {'', ' ', ' \n ', '\ufeff'}:
#         chgk_parse(elem)
#         parse_4s(elem)

def test_canonical_equality():
    for filename in os.listdir(currentdir):
        if filename.endswith('.canon'):
            print('Testing {}...'.format(filename[:-6]))
            parsed = workaround_chgk_parse(os.path.join(
                currentdir, filename[:-6]))
            for filename1 in os.listdir(currentdir):
                if (filename1.endswith(('.jpg', '.jpeg', '.png', '.gif'))
                    and not filename1.startswith('ALLOWED')):
                    os.remove(os.path.join(currentdir, filename1))
            with codecs.open(os.path.join(currentdir, filename), 
                'r', 'utf8') as f:
                canonical = f.read()
            assert compose_4s(parsed) == canonical