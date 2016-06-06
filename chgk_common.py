#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import sys
import codecs
import argparse


QUESTION_LABELS = ['handout', 'question', 'answer',
                   'zachet', 'nezachet', 'comment',
                   'source', 'author', 'number',
                   'setcounter']
SEP = os.linesep

lastdir = os.path.join(os.path.dirname(os.path.abspath('__file__')),
                       'lastdir')


def set_lastdir(path):
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if os.path.isdir(path):
        with codecs.open(lastdir, 'w', 'utf8') as f:
            f.write(path)


def get_lastdir():
    if os.path.isfile(lastdir):
        with codecs.open(lastdir, 'r', 'utf8') as f:
            return f.read().rstrip()
    return '.'


class DummyLogger(object):

    def info(self, s):
        pass

    def debug(self, s):
        pass

    def error(self, s):
        pass

    def warning(self, s):
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


def on_close(root):
    root.quit()
    root.destroy()


def log_wrap(s):
    s = format(s)
    if sys.version_info.major == 2:
        s = s.decode('unicode_escape')
    return s.encode(sys.stdout.encoding,
                    errors='replace').decode(sys.stdout.encoding)


def toggle_factory(intvar, strvar, root):
    def toggle():
        if intvar.get() == 0:
            intvar.set(1)
        else:
            intvar.set(0)
        root.ret[strvar] = bool(intvar.get())
    return toggle


def button_factory(strvar, value, root):
    def button():
        root.ret[strvar] = value
        root.quit()
        root.destroy()
    return button


def check_question(question, logger=None):
    warnings = []
    for el in {'question', 'answer', 'source', 'author'}:
        if el not in question:
            warnings.append(el)
    if len(warnings) > 0:
        logger.warning('WARNING: question {} lacks the following fields: {}{}'
                       .format(log_wrap(question), ', '.join(warnings), SEP))
