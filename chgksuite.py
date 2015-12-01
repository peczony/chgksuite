#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import os
import pdb
from chgk_parser import gui_parse
from chgk_composer import gui_compose

try:
    from Tkinter import *
except:
    from tkinter import *
import tkFileDialog
import tkFont

debug = False

def info(type, value, tb):
   if hasattr(sys, 'ps1') or not sys.stderr.isatty():
      # we are in interactive mode or we don't have a tty-like
      # device, so we call the default hook
      sys.__excepthook__(type, value, tb)
   else:
      import traceback, pdb
      # we are NOT in interactive mode, print the exception...
      traceback.print_exception(type, value, tb)
      print
      # ...then start the debugger in post-mortem mode.
      pdb.pm()
sys.excepthook = info

def gui_choose_action():
        def parsereturn():
            root.ret = 'parse'
            root.quit()
            root.destroy()
        def composereturn():
            root.ret = 'compose'
            root.quit()
            root.destroy()
        root = Tk()
        root.eval('tk::PlaceWindow {} center'.format(
            root.winfo_pathname(root.winfo_id())))
        root.ret = 'None'
        frame = Frame(root)
        frame.pack()
        bottomframe = Frame(root)
        bottomframe.pack(side = 'bottom')
        Button(frame, command=
            parsereturn, text = 'Parse').pack(side = 'left', 
            padx = 20, pady = 20,
            ipadx = 20, ipady = 20,)
        Button(frame, command=
            composereturn, text = 'Compose').pack(side = 'left',
            padx = 20, pady = 20,
            ipadx = 20, ipady = 20,)
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
    parser.add_argument('--login', '-l')
    parser.add_argument('--password', '-p')
    parser.add_argument('--community', '-c')
    args = parser.parse_args()
    
    if not args.action:
        args.action = gui_choose_action()
    if args.action == 'parse':
        gui_parse(args)
    if args.action == 'compose':
        gui_compose(args, sourcedir=os.path.dirname(
            os.path.abspath(__file__)))

if __name__ == "__main__":
    main()