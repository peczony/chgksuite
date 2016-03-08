#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import os
import pdb
import sys

try:
    from Tkinter import Tk, Frame, IntVar, Button, Checkbutton
except ImportError:
    from tkinter import Tk, Frame, IntVar, Button, Checkbutton

from chgk_parser import gui_parse
from chgk_composer import gui_compose, on_close

debug = False

def gui_choose_action(args):
    ch_defaultauthor = IntVar()
    try:
        ch_defaultauthor.set(int(args.defaultauthor))
    except TypeError:
        ch_defaultauthor.set(0)
    ch_merge = IntVar()
    try:
        ch_merge.set(int(args.merge))
    except TypeError:
        ch_merge.set(0)
    def parsereturn():
        root.ret = 'parse', ch_defaultauthor.get(), ch_merge.get()
        root.quit()
        root.destroy()
    def parsedirreturn():
        root.ret = 'parsedir', ch_defaultauthor.get(), ch_merge.get()
        root.quit()
        root.destroy()
    def composereturn():
        root.ret = 'compose', ch_defaultauthor.get(), ch_merge.get()
        root.quit()
        root.destroy()
    def toggle_da():
        if ch_defaultauthor.get() == 0:
            ch_defaultauthor.set(1)
        else:
            ch_defaultauthor.set(0)
    def toggle_mrg():
        if ch_merge.get() == 0:
            ch_merge.set(1)
        else:
            ch_merge.set(0)
    root = Tk()
    root.title('chgksuite')
    root.eval('tk::PlaceWindow {} center'.format(
        root.winfo_pathname(root.winfo_id())))
    root.ret = 'None', '0'
    root.grexit = lambda: on_close(root)
    root.protocol("WM_DELETE_WINDOW", root.grexit)
    root.attributes("-topmost", True)
    frame = Frame(root)
    frame.pack()
    bottomframe = Frame(root)
    bottomframe.pack(side = 'bottom')
    Button(frame, command=
        parsereturn, text = 'Parse file(s)').pack(side = 'left',
        padx = 20, pady = 20,
        ipadx = 20, ipady = 20,)
    Button(frame, command=
        parsedirreturn, text = 'Parse directory').pack(side = 'left',
        padx = 20, pady = 20,
        ipadx = 20, ipady = 20,)
    Button(frame, command=
        composereturn, text = 'Compose').pack(side = 'left',
        padx = 20, pady = 20,
        ipadx = 20, ipady = 20,)
    da = Checkbutton(bottomframe, text='Default author while parsing',
        variable=ch_defaultauthor, command=toggle_da)
    mrg = Checkbutton(bottomframe, text='Merge several source files',
        variable=ch_merge, command=toggle_mrg)
    if ch_defaultauthor.get() == 1:
        da.select()
    if ch_merge.get() == 1:
        mrg.select()
    mrg.pack(side = 'bottom')
    da.pack(side = 'bottom')
    root.mainloop()
    return root.ret

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

def main():
    parser = argparse.ArgumentParser(prog='chgksuite')
    parser.add_argument('--debug', '-d', action='store_true',
        help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest='action')

    cmdparse = subparsers.add_parser('parse')
    cmdparse.add_argument('filename', help='file to parse.',
        nargs='?')
    cmdparse.add_argument('--defaultauthor', action='store_true',
        help='pick default author from filename where author is missing.')
    cmdparse.add_argument('--parsedir', action='store_true',
        help='parse directory instead of file.')

    cmdcompose = subparsers.add_parser('compose')
    cmdcompose.add_argument('--merge', action='store_true',
        help='merge several source files before output.')
    cmdcompose_filetype = cmdcompose.add_subparsers(dest='filetype')
    cmdcompose_docx = cmdcompose_filetype.add_parser('docx')
    cmdcompose_docx.add_argument('filename', nargs='*',
        help='file(s) to compose from.')
    cmdcompose_docx.add_argument('--nospoilers', '-n', action='store_true',
        help='do not whiten (spoiler) answers.')
    cmdcompose_docx.add_argument('--noanswers', action='store_true',
        help='do not print answers (not even spoilered).')
    cmdcompose_docx.add_argument('--noparagraph', action='store_true',
        help='disable paragraph break after \'Question N.\'')
    cmdcompose_docx.add_argument('--randomize', action='store_true',
        help='randomize order of questions.')

    cmdcompose_tex = cmdcompose_filetype.add_parser('tex')
    cmdcompose_tex.add_argument('filename', nargs='*',
        help='file(s) to compose from.')
    cmdcompose_tex.add_argument('--rawtex', action='store_true')

    cmdcompose_lj = cmdcompose_filetype.add_parser('lj')
    cmdcompose_lj.add_argument('filename', nargs='*',
        help='file(s) to compose from.')
    cmdcompose_lj.add_argument('--nospoilers', '-n', action='store_true',
        help='disable spoilers.')
    cmdcompose_lj.add_argument('--splittours', action='store_true',
        help='make a separate post for each tour.')
    cmdcompose_lj.add_argument('--genimp', action='store_true',
        help='make a \'general impressions\' post.')
    cmdcompose_lj.add_argument('--login', '-l',
        help='livejournal login')
    cmdcompose_lj.add_argument('--password', '-p',
        help='livejournal password')
    cmdcompose_lj.add_argument('--community', '-c',
        help='livejournal community to post to.')

    if len(sys.argv) == 1:
        args = DefaultNamespace()
    else:
        args = DefaultNamespace(parser.parse_args())

    root = Tk()
    root.withdraw()

    if not args.action:
        action, defaultauthor, merge = gui_choose_action(args)
        if action == 'parse':
            args.action = 'parse'
            args.defaultauthor = defaultauthor
        if action == 'parsedir':
            args.action = 'parse'
            args.defaultauthor = defaultauthor
            args.parsedir = True
        if action == 'compose':
            args.action = 'compose'
            args.merge = merge
    if args.action == 'parse':
        gui_parse(args)
    if args.action == 'compose':
        gui_compose(args, sourcedir=os.path.dirname(
            os.path.abspath(__file__)))

if __name__ == "__main__":
    main()
