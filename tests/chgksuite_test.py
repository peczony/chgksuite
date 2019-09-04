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
    os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir)

from chgk_parser import chgk_parse, chgk_parse_txt, chgk_parse_docx, compose_4s
from chgk_composer import parse_4s

class DefaultArgs(object):
    links = "unwrap"
    fix_spans = False

ljlogin, ljpassword = open(
    os.path.join(currentdir, 'ljcredentials')).read().split('\t')

def workaround_chgk_parse(filename):
    if filename.endswith('.txt'):
        return chgk_parse_txt(filename)
    elif filename.endswith('.docx'):
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
    return string.replace('\r\n', '\n')

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
            assert normalize(canonical) == normalize(compose_4s(parsed))

def test_composition():
    for filename in os.listdir(currentdir):
        if filename.endswith(('.docx', '.txt')) and filename == 'Kubok_knyagini_Olgi-2015.docx':
            print('Testing {}...'.format(filename))
            with make_temp_directory(dir='.') as temp_dir:
                shutil.copy(os.path.join(currentdir, filename), temp_dir)
                os.chdir(temp_dir)
                parsed = workaround_chgk_parse(filename)
                file4s = os.path.splitext(filename)[0]+'.4s'
                with codecs.open(
                    file4s,'w','utf8') as f:
                    f.write(compose_4s(parsed))
                abspath = os.path.abspath(file4s)
                os.chdir(currentdir)
                os.chdir('..')
                subprocess.call(['python', 'chgksuite.py', 'compose',
                    '{}'.format(abspath), 'docx'])
                subprocess.call(['python', 'chgksuite.py', 'compose',
                    '{}'.format(abspath), 'tex'])
                # subprocess.call(['python', 'chgksuite.py', 'compose',
                #     '{}'.format(abspath), 'lj', '-l', ljlogin, '-p', ljpassword])
                os.chdir(currentdir)
