#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import os
import sys

try:
    import Tkinter as tk
except ImportError:
    import tkinter as tk

from chgk_parser import gui_parse
from chgk_composer import gui_compose
from chgk_trello import gui_trello
from chgk_common import (
    on_close,
    button_factory,
    toggle_factory,
    DefaultNamespace,
    bring_to_front,
)

from collections import defaultdict
import json

try:
    basestring
except NameError:
    basestring = (str, bytes)

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
    ch_passthrough = IntVar()
    ch_passthrough.set(0)

    root = Tk()
    root.title("chgksuite")
    root.eval("tk::PlaceWindow . center")
    root.ret = defaultdict(lambda: None)
    root.grexit = lambda: on_close(root)
    root.protocol("WM_DELETE_WINDOW", root.grexit)
    root.attributes("-topmost", True)
    frame = Frame(root)
    frame.pack()
    bottomframe = Frame(root)
    bottomframe.pack(side="bottom")
    midframe = Frame(root)
    midframe.pack(side="bottom")
    Button(
        frame, command=button_factory("action", "parse", root), text="Parse file(s)"
    ).pack(side="left", padx=20, pady=20, ipadx=20, ipady=20)
    Button(
        frame,
        command=button_factory("action", "parsedir", root),
        text="Parse directory",
    ).pack(side="left", padx=20, pady=20, ipadx=20, ipady=20)
    Button(
        frame, command=button_factory("action", "compose", root), text="Compose"
    ).pack(side="left", padx=20, pady=20, ipadx=20, ipady=20)
    Button(
        bottomframe,
        command=button_factory("action", "trellodown", root),
        text="Download from Trello",
    ).pack(side="left", padx=20, pady=20, ipadx=20, ipady=20)
    Button(
        bottomframe,
        command=button_factory("action", "trelloup", root),
        text="Upload to Trello",
    ).pack(side="left", padx=20, pady=20, ipadx=20, ipady=20)
    Button(
        bottomframe,
        command=button_factory("action", "trellotoken", root),
        text="Obtain a token",
    ).pack(side="left", padx=20, pady=20, ipadx=20, ipady=20)
    da = Checkbutton(
        midframe,
        text="Default author while parsing",
        variable=ch_defaultauthor,
        command=toggle_factory(ch_defaultauthor, "defaultauthor", root),
    )
    mrg = Checkbutton(
        midframe,
        text="Merge several source files",
        variable=ch_merge,
        command=toggle_factory(ch_merge, "merge", root),
    )
    pt = Checkbutton(
        midframe,
        text="Pass through to compose",
        variable=ch_passthrough,
        command=toggle_factory(ch_passthrough, "passthrough", root),
    )
    if ch_defaultauthor.get() == 1:
        da.select()
    root.ret["defaultauthor"] = bool(ch_defaultauthor.get())
    if ch_merge.get() == 1:
        mrg.select()
    root.ret["merge"] = bool(ch_merge.get())
    mrg.pack(side="bottom")
    da.pack(side="bottom")
    pt.pack(side="bottom")
    bring_to_front(root)
    root.mainloop()
    return root.ret


class VarWrapper(object):
    def __init__(self, name, var):
        self.name = name
        self.var = var


class OpenFileDialog(object):
    def __init__(self, label, var):
        self.label = label
        self.var = var

    def __call__(self):
        filename = tk.filedialog.askopenfilename()
        self.var.set(filename or "")
        self.label.config(text=filename or "")


class ParserWrapper(object):
    def __init__(self, parser, parent=None):
        self.parent = parent
        if self.parent:
            self.parent.children.append(self)
            self.frame = tk.Frame(self.parent.frame)
        else:
            self.init_tk()
        self.parser = parser
        self.children = []
        self.vars = []

    def init_tk(self):
        self.tk = tk.Tk()
        self.tk.title("chgksuite")
        self.frame = tk.Frame(self.tk)
        self.frame.pack()

    def add_argument(self, *args, **kwargs):

        if kwargs.get("action") == "store_true":
            var = tk.StringVar()
            var.set("false")
            checkbutton = tk.Checkbutton(
                self.frame,
                text=args[0],
                variable=var,
                onvalue="true",
                offvalue="false"
            )
            checkbutton.pack(side="top")
            self.vars.append(VarWrapper(name=args[0], var=var))
        elif args[0] == "filename":
            var = tk.StringVar()
            label = tk.Label(
                self.frame,
                text="",
            )
            label.pack(side="top")
            button = tk.Button(
                self.frame,
                text="Open file",
                command=OpenFileDialog(label, var)
            )
            button.pack(side="top")
            self.vars.append(VarWrapper(name=args[0], var=var))
        else:
            var = tk.StringVar()
            var.set(kwargs.get("default") or "")
            tk.Label(
                self.frame, text=args[0]
            ).pack(side="top")
            entry = tk.Entry(
                self.frame,
                textvariable=var
            )
            entry.pack(side="top")
            self.vars.append(VarWrapper(name=args[0], var=var))
        self.parser.add_argument(*args, **kwargs)

    def add_subparsers(self, *args, **kwargs):
        subparsers = self.parser.add_subparsers(*args, **kwargs)
        self.subparsers_var = tk.StringVar()
        self.subparsers = SubparsersWrapper(subparsers, parent=self)
        return self.subparsers

    def show_frame(self):
        for child in self.parent.children:
            child.frame.pack_forget()
        self.frame.pack(side="top")

    def parse_args(self, *args, **kwargs):
        argv = sys.argv[1:]
        if not argv:
            self.tk.mainloop()
            sys.exit(0)
        return DefaultNamespace(self.parser.parse_args(*args, **kwargs))


class SubparsersWrapper(object):
    def __init__(self, subparsers, parent):
        self.subparsers = subparsers
        self.parent = parent

    def add_parser(self, *args, **kwargs):
        parser = self.subparsers.add_parser(*args, **kwargs)
        pw = ParserWrapper(parser=parser, parent=self.parent)
        radio = tk.Radiobutton(
            self.parent.frame,
            text=args[0],
            variable=self.parent.subparsers_var,
            value=args[0],
            command=pw.show_frame
        )
        radio.pack(side="top")
        return pw


def main():
    parser = ParserWrapper(argparse.ArgumentParser(prog="chgksuite"))
    parser.add_argument("--debug", "-d", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--config", "-c", help="a config file to store default args values."
    )
    subparsers = parser.add_subparsers(dest="action")

    cmdparse = subparsers.add_parser("parse")
    cmdparse.add_argument("filename", help="file to parse.", nargs="?")
    cmdparse.add_argument(
        "--defaultauthor",
        action="store_true",
        help="pick default author from filename " "where author is missing.",
    )
    cmdparse.add_argument(
        "--encoding",
        default=None,
        help="Encoding of text file " "(use if auto-detect fails).",
    )
    cmdparse.add_argument(
        "--regexes",
        default=None,
        help="A file containing regexes " "(the default is regexes.json).",
    )
    cmdparse.add_argument(
        "--parsedir", action="store_true", help="parse directory instead of file."
    )
    cmdparse.add_argument(
        "--links",
        default="unwrap",
        choices=["unwrap", "old"],
        help="hyperlinks handling strategy. "
        "Unwrap just leaves links as presented in the text, unchanged. "
        "Old is behaviour from versions up to v0.5.3: "
        "replace link with its href value.",
    )
    cmdparse.add_argument(
        "--fix_spans",
        action="store_true",
        help="sometimes it will fix weird Word formatting. "
        "Other times it will do harm.",
    )

    cmdcompose = subparsers.add_parser("compose")
    cmdcompose.add_argument(
        "--merge", action="store_true", help="merge several source files before output."
    )
    cmdcompose.add_argument(
        "--nots", action="store_true", help="don't append timestamp to filenames"
    )
    cmdcompose_filetype = cmdcompose.add_subparsers(dest="filetype")
    cmdcompose_docx = cmdcompose_filetype.add_parser("docx")
    cmdcompose_docx.add_argument("--docx_template", help="a DocX template file.")
    cmdcompose_docx.add_argument("filename", nargs="*", help="file(s) to compose from.")
    cmdcompose_docx.add_argument(
        "--nospoilers",
        "-n",
        action="store_true",
        help="do not whiten (spoiler) answers.",
    )
    cmdcompose_docx.add_argument(
        "--noanswers",
        action="store_true",
        help="do not print answers " "(not even spoilered).",
    )
    cmdcompose_docx.add_argument(
        "--noparagraph",
        action="store_true",
        help="disable paragraph break " "after 'Question N.'",
    )
    cmdcompose_docx.add_argument(
        "--randomize", action="store_true", help="randomize order of questions."
    )
    cmdcompose_docx.add_argument(
        "--add_line_break",
        action="store_true",
        help="add line break between question and answer.",
    )

    cmdcompose_tex = cmdcompose_filetype.add_parser("tex")
    cmdcompose_tex.add_argument("--tex_header", help="a LaTeX header file.")
    cmdcompose_tex.add_argument("filename", nargs="*", help="file(s) to compose from.")
    cmdcompose_tex.add_argument("--rawtex", action="store_true")

    cmdcompose_lj = cmdcompose_filetype.add_parser("lj")
    cmdcompose_lj.add_argument("filename", nargs="*", help="file(s) to compose from.")
    cmdcompose_lj.add_argument(
        "--nospoilers", "-n", action="store_true", help="disable spoilers."
    )
    cmdcompose_lj.add_argument(
        "--splittours", action="store_true", help="make a separate post for each tour."
    )
    cmdcompose_lj.add_argument(
        "--genimp", action="store_true", help="make a 'general impressions' post."
    )
    cmdcompose_lj.add_argument("--login", "-l", help="livejournal login")
    cmdcompose_lj.add_argument("--password", "-p", help="livejournal password")
    cmdcompose_lj.add_argument(
        "--community", "-c", help="livejournal community to post to."
    )
    cmdcompose_base = cmdcompose_filetype.add_parser("base")
    cmdcompose_base.add_argument("filename", nargs="*", help="file(s) to compose from.")
    cmdcompose_base.add_argument("--clipboard", action="store_true")
    cmdcompose_redditmd = cmdcompose_filetype.add_parser("redditmd")
    cmdcompose_redditmd.add_argument(
        "filename", nargs="*", help="file(s) to compose from."
    )

    cmdtrello = subparsers.add_parser("trello")
    cmdtrello_subcommands = cmdtrello.add_subparsers(dest="trellosubcommand")
    cmdtrello_download = cmdtrello_subcommands.add_parser("download")
    cmdtrello_download.add_argument(
        "folder", help="path to the folder" "to synchronize with a trello board."
    )
    cmdtrello_download.add_argument(
        "--si",
        action="store_true",
        help="This flag includes card captions "
        "in .4s files. "
        "Useful for editing SI "
        "files (rather than CHGK)",
    )
    cmdtrello_download.add_argument(
        "--onlyanswers",
        action="store_true",
        help="This flag forces SI download to only include answers.",
    )
    cmdtrello_download.add_argument(
        "--noanswers",
        action="store_true",
        help="This flag forces SI download to not include answers.",
    )
    cmdtrello_download.add_argument(
        "--singlefile",
        action="store_true",
        help="This flag forces SI download all themes to single file.",
    )
    cmdtrello_download.add_argument("--qb", nargs="+", help="Quizbowl format")
    cmdtrello_download.add_argument(
        "--labels",
        action="store_true",
        help="Use this if you also want " "to have lists based on labels.",
    )

    cmdtrello_upload = cmdtrello_subcommands.add_parser("upload")
    cmdtrello_upload.add_argument("board_id", help="trello board id.")
    cmdtrello_upload.add_argument(
        "filename", nargs="*", help="file(s) to upload to trello."
    )
    cmdtrello_upload.add_argument(
        "--author", action="store_true", help="Display authors in cards' captions"
    )

    cmdtrello_subcommands.add_parser("token")

    args = parser.parse_args()
    import pdb

    pdb.set_trace()

    root = Tk()
    root.withdraw()

    sourcedir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))

    if not args.regexes:
        args.regexes = os.path.join(sourcedir, "regexes.json")
    if not args.docx_template:
        args.docx_template = os.path.join(sourcedir, "template.docx")
    if not args.tex_header:
        args.tex_header = os.path.join(sourcedir, "cheader.tex")
    if args.config:
        with open(args.config, "r") as f:
            config = json.load(f)
        for key in config:
            if not isinstance(config[key], basestring):
                val = config[key]
            elif os.path.isfile(config[key]):
                val = os.path.abspath(config[key])
            elif os.path.isfile(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), config[key])
            ):
                val = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), config[key]
                )
            else:
                val = config[key]
            setattr(args, key, val)

    args.passthrough = False
    if not args.action:
        try:
            ret = gui_choose_action(args)
            action = ret["action"]
            defaultauthor = ret["defaultauthor"]
            merge = ret["merge"]
            passthrough = ret["passthrough"]
        except ValueError:
            sys.exit(1)
        if passthrough:
            args.passthrough = True
        if action == "parse":
            args.action = "parse"
            args.defaultauthor = defaultauthor
        if action == "parsedir":
            args.action = "parse"
            args.defaultauthor = defaultauthor
            args.parsedir = True
        if action == "compose":
            args.action = "compose"
            args.merge = merge
        if action == "trellodown":
            args.action = "trello"
            args.trellosubcommand = "download"
        if action == "trelloup":
            args.action = "trello"
            args.trellosubcommand = "upload"
        if action == "trellotoken":
            args.action = "trello"
            args.trellosubcommand = "token"
    if args.action == "parse":
        gui_parse(args, sourcedir=sourcedir)
    if args.action == "compose":
        gui_compose(args, sourcedir=sourcedir)
    if args.action == "trello":
        gui_trello(args, sourcedir=sourcedir)


if __name__ == "__main__":
    main()
