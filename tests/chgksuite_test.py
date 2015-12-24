#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import codecs
import os
import pdb
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

ljlogin, ljpassword = open(
    os.path.join(currentdir, 'ljcredentials')).read().split('\t')

def workaround_chgk_parse(filename):
    if filename.endswith(b'.txt'):
        return chgk_parse_txt(filename)
    elif filename.endswith(b'.docx'):
        return chgk_parse_docx(filename)
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

def test_canonical_equality():
    for filename in os.listdir(currentdir):
        if filename.endswith(b'.canon'):
            print(b'Testing {}...'.format(filename[:-6]))
            parsed = workaround_chgk_parse(os.path.join(
                currentdir, filename[:-6]))
            for filename1 in os.listdir(currentdir):
                if (filename1.endswith((b'.jpg', b'.jpeg', b'.png', b'.gif'))
                    and not filename1.startswith(b'ALLOWED')):
                    os.remove(os.path.join(currentdir, filename1))
            with codecs.open(os.path.join(currentdir, filename), 
                'r', 'utf8') as f:
                canonical = f.read()
            assert compose_4s(parsed) == canonical

def test_composition():
    for filename in os.listdir(currentdir):
        if filename.endswith((b'.docx', b'.txt')) and filename == b'Kubok_knyagini_Olgi-2015.docx':
            print(b'Testing {}...'.format(filename))
            with make_temp_directory(dir='.') as temp_dir:
                shutil.copy(os.path.join(currentdir, filename), temp_dir)
                os.chdir(temp_dir)
                parsed = workaround_chgk_parse(filename)
                file4s = os.path.splitext(filename)[0]+b'.4s'
                with codecs.open(
                    file4s,'w','utf8') as f:
                    f.write(compose_4s(parsed))
                abspath = os.path.abspath(file4s)
                os.chdir(currentdir)
                os.chdir('..')
                subprocess.call([b'python', b'chgksuite.py', b'compose',
                    b'{}'.format(abspath), b'docx'])
                subprocess.call([b'python', b'chgksuite.py', b'compose',
                    b'{}'.format(abspath), b'tex'])
                # subprocess.call([b'python', b'chgksuite.py', b'compose',
                #     b'{}'.format(abspath), b'lj', b'-l', ljlogin, b'-p', ljpassword])
                os.chdir(currentdir)