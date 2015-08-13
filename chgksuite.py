#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import os
from chgk_parser import gui_parse
from chgk_composer import gui_compose

try:
    from Tkinter import *
except:
    from tkinter import *
import tkFileDialog
import tkFont

debug = False

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
    action = gui_choose_action()
    if action == 'parse':
        gui_parse()
    if action == 'compose':
        gui_compose()

if __name__ == "__main__":
    main()