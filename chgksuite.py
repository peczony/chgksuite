#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import os
import pdb
from chgk_parser import gui_parse
from chgk_composer import gui_compose, on_close

try:
    from Tkinter import Tk, Frame, IntVar, Button, Checkbutton, Entry, Label
except:
    from tkinter import Tk, Frame, IntVar, Button, Checkbutton, Entry, Label
import tkFileDialog
import tkFont

debug = False

def gui_choose_action(args):
    ch_defaultauthor = IntVar()
    if args.defaultauthor:
        ch_defaultauthor.set(1)
    else:
        ch_defaultauthor.set(0)
    def parsereturn():
        root.ret = 'parse', ch_defaultauthor.get()
        root.quit()
        root.destroy()
    def parsedirreturn():
        root.ret = 'parsedir', ch_defaultauthor.get()
        root.quit()
        root.destroy()
    def composereturn():
        root.ret = 'compose', ch_defaultauthor.get()
        root.quit()
        root.destroy()
    def toggle_da():
        if ch_defaultauthor.get() == 0:
            ch_defaultauthor.set(1)
        else:
            ch_defaultauthor.set(0)
    root = Tk()
        root.title('chgksuite')
    root.eval('tk::PlaceWindow {} center'.format(
        root.winfo_pathname(root.winfo_id())))
    root.ret = 'None', '0'
    root.grexit = lambda: on_close(root)
    root.protocol("WM_DELETE_WINDOW", root.grexit)
    frame = Frame(root)
    frame.pack()
    bottomframe = Frame(root)
    bottomframe.pack(side = 'bottom')
    Button(frame, command=
        parsereturn, text = 'Parse file').pack(side = 'left', 
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
    if args.defaultauthor:
        da.select()
    da.pack(side = 'bottom')
    root.mainloop()
    return root.ret

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?')
    parser.add_argument('filename', nargs='?')
    parser.add_argument('filetype', nargs='?')
    parser.add_argument('--debug', '-d', action='store_true')
    parser.add_argument('--nospoilers', '-n', action='store_true')
    parser.add_argument('--noanswers', action='store_true')
    parser.add_argument('--noparagraph', action='store_true')
    parser.add_argument('--randomize', action='store_true')
    parser.add_argument('--rawtex', action='store_true')
    parser.add_argument('--parsedir', action='store_true')
    parser.add_argument('--defaultauthor', action='store_true')
    parser.add_argument('--login', '-l')
    parser.add_argument('--password', '-p')
    parser.add_argument('--community', '-c')
    args = parser.parse_args()

    root = Tk()
    root.withdraw()
    
    if not args.action:
        args.action, args.defaultauthor = gui_choose_action(args)
    if args.action == 'parse':
        gui_parse(args)
    if args.action == 'parsedir':
        args.parsedir = True
        gui_parse(args)
    if args.action == 'compose':
        gui_compose(args, sourcedir=os.path.dirname(
            os.path.abspath(__file__)))

if __name__ == "__main__":
    main()