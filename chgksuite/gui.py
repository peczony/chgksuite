#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import os
import sys

try:
    import Tkinter as tk
    import Tkinter.filedialog as filedialog
    import Tkinter.ttk as ttk
except ImportError:
    import tkinter as tk
    import tkinter.filedialog as filedialog
    import tkinter.ttk as ttk

from chgksuite.parser import gui_parse
from chgksuite.composer import gui_compose
from chgksuite.trello import gui_trello
from chgksuite.version import __version__
from chgksuite.common import (
    on_close,
    button_factory,
    toggle_factory,
    DefaultNamespace,
    bring_to_front,
    get_lastdir,
    ensure_utf8,
    get_source_dirs
)

from collections import defaultdict
import json

try:
    basestring
except NameError:
    basestring = (str, bytes)

debug = False


class VarWrapper(object):
    def __init__(self, name, var):
        self.name = name
        self.var = var


class OpenFileDialog(object):
    def __init__(self, label, var, folder=False, lastdir=None, filetypes=None):
        self.label = label
        self.var = var
        self.folder = folder
        self.lastdir = lastdir
        self.filetypes = filetypes

    def __call__(self):
        function = (
            filedialog.askdirectory
            if self.folder
            else filedialog.askopenfilename
        )
        kwargs = {}
        if self.lastdir:
            kwargs["initialdir"] = self.lastdir
        if self.filetypes:
            kwargs["filetypes"] = self.filetypes
        output = function(**kwargs)
        if isinstance(output, bytes):
            output = output.decode("utf8")
        self.var.set(output or "")
        self.label.config(text=(output or "").split(ensure_utf8(os.sep))[-1])


class ParserWrapper(object):
    def __init__(self, parser, parent=None, lastdir=None):
        self.parent = parent
        if self.parent and not lastdir:
            self.lastdir = self.parent.lastdir
        else:
            self.lastdir = lastdir
        if self.parent:
            self.parent.children.append(self)
            self.frame = tk.Frame(self.parent.frame)
            self.frame.pack()
            self.frame.pack_forget()
            self.advanced_frame = tk.Frame(self.parent.advanced_frame)
            self.advanced_frame.pack()
            self.advanced_frame.pack_forget()
        else:
            self.init_tk()
        self.parser = parser
        self.subparsers_var = None
        self.cmdline_call = None
        self.children = []
        self.vars = []

    def _list_vars(self):
        result = []
        for var in self.vars:
            result.append((var.name, var.var.get()))
        if self.subparsers_var:
            chosen_parser_name = self.subparsers_var.get()
            chosen_parser = [
                x
                for x in self.subparsers.parsers
                if x.parser.prog.split()[-1] == chosen_parser_name
            ][0]
            result.append(("", chosen_parser_name))
            result.extend(chosen_parser._list_vars())
        return result

    def build_command_line_call(self):
        result = []
        result_to_print = []
        for tup in self._list_vars():
            to_append = None
            if tup[0].startswith("--"):
                if tup[1] == "true":
                    to_append = tup[0]
                elif not tup[1] or tup[1] == "false":
                    continue
                else:
                    to_append = [tup[0], tup[1]]
            else:
                to_append = tup[1]
            if isinstance(to_append, list):
                result.extend(to_append)
                if "password" in tup[0]:
                    result_to_print.append(tup[0])
                    result_to_print.append("********")
                else:
                    result_to_print.extend(to_append)
            else:
                result.append(to_append)
                result_to_print.append(to_append)
        print("Command line call: {}".format(" ".join(result_to_print)))
        return result

    def ok_button_press(self):
        self.cmdline_call = self.build_command_line_call()
        self.tk.quit()
        self.tk.destroy()

    def toggle_advanced_frame(self):
        value = self.advanced_checkbox_var.get()
        if value == "true":
            self.advanced_frame.pack()
        else:
            self.advanced_frame.pack_forget()

    def init_tk(self):
        self.tk = tk.Tk()
        self.tk.title("chgksuite v{}".format(__version__))
        self.tk.minsize(600, 300)
        self.tk.eval("tk::PlaceWindow . center")
        self.mainframe = tk.Frame(self.tk)
        self.mainframe.pack(side="top")
        self.frame = tk.Frame(self.mainframe)
        self.frame.pack(side="top")
        self.button_frame = tk.Frame(self.mainframe)
        self.button_frame.pack(side="top")
        self.ok_button = tk.Button(
            self.button_frame,
            text="Запустить",
            command=self.ok_button_press,
            width=15,
            height=2,
        )
        self.ok_button.pack(side="top")
        self.advanced_checkbox_var = tk.StringVar()
        self.toggle_advanced_checkbox = tk.Checkbutton(
            self.button_frame,
            text="Показать дополнительные настройки",
            onvalue="true",
            offvalue="false",
            variable=self.advanced_checkbox_var,
            command=self.toggle_advanced_frame,
        )
        self.toggle_advanced_checkbox.pack(side="top")
        self.advanced_frame = tk.Frame(self.mainframe)
        self.advanced_frame.pack(side="top")
        self.advanced_frame.pack_forget()

    def add_argument(self, *args, **kwargs):

        if kwargs.pop("advanced", False):
            frame = self.advanced_frame
        else:
            frame = self.frame
        if kwargs.pop("hide", False):
            self.parser.add_argument(*args, **kwargs)
            return
        caption = kwargs.pop("caption", None) or args[0]
        argtype = kwargs.pop("argtype", None)
        filetypes = kwargs.pop("filetypes", None)
        if not argtype:
            if kwargs.get("action") == "store_true":
                argtype = "checkbutton"
            elif args[0] in {"filename", "folder"}:
                argtype = args[0]
            else:
                argtype = "entry"
        if argtype == "checkbutton":
            var = tk.StringVar()
            var.set("false")
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            checkbutton = tk.Checkbutton(
                innerframe,
                text=caption,
                variable=var,
                onvalue="true",
                offvalue="false",
            )
            checkbutton.pack(side="left")
            self.vars.append(VarWrapper(name=args[0], var=var))
        elif argtype in {"filename", "folder"}:
            text = "(имя файла)" if argtype == "filename" else "(имя папки)"
            button_text = (
                "Открыть файл" if argtype == "filename" else "Открыть папку"
            )
            var = tk.StringVar()
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            label = tk.Label(innerframe, text=caption)
            label.pack(side="left")
            label = tk.Label(innerframe, text=text)
            ofd_kwargs = dict(folder=argtype == "folder", lastdir=self.lastdir)
            if filetypes:
                ofd_kwargs["filetypes"] = filetypes
            button = tk.Button(
                innerframe,
                text=button_text,
                command=OpenFileDialog(label, var, **ofd_kwargs),
            )
            button.pack(side="left")
            label.pack(side="left")
            self.vars.append(VarWrapper(name=args[0], var=var))
        elif argtype == "entry":
            var = tk.StringVar()
            var.set(kwargs.get("default") or "")
            innerframe = tk.Frame(frame)
            innerframe.pack(side="top")
            tk.Label(innerframe, text=caption).pack(side="left")
            entry_show = "*" if "password" in args[0] else ""
            entry = tk.Entry(innerframe, textvariable=var, show=entry_show)
            entry.pack(side="left")
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
            child.advanced_frame.pack_forget()
        self.frame.pack(side="top")
        self.advanced_frame.pack(side="top")

    def parse_args(self, *args, **kwargs):
        argv = sys.argv[1:]
        if not argv:
            self.tk.mainloop()
            if self.cmdline_call:
                return DefaultNamespace(
                    self.parser.parse_args(self.cmdline_call)
                )
            else:
                sys.exit(0)
        return DefaultNamespace(self.parser.parse_args(*args, **kwargs))


class SubparsersWrapper(object):
    def __init__(self, subparsers, parent):
        self.subparsers = subparsers
        self.parent = parent
        self.frame = tk.Frame(self.parent.frame)
        self.frame.pack(side="top")
        self.parsers = []

    def add_parser(self, *args, **kwargs):
        caption = kwargs.pop("caption", None) or args[0]
        parser = self.subparsers.add_parser(*args, **kwargs)
        pw = ParserWrapper(parser=parser, parent=self.parent)
        self.parsers.append(pw)
        radio = tk.Radiobutton(
            self.frame,
            text=caption,
            variable=self.parent.subparsers_var,
            value=args[0],
            command=pw.show_frame,
        )
        radio.pack(side="left")
        return pw


def app():
    sourcedir, resourcedir = get_source_dirs()

    if isinstance(sourcedir, bytes):
        sourcedir = sourcedir.decode("utf8")
    ld = get_lastdir()
    parser = ParserWrapper(
        argparse.ArgumentParser(prog="chgksuite".format(__version__)), lastdir=ld
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Print and save some debug info.",
        caption="Отладочная информация",
        advanced=True,
    )
    parser.add_argument(
        "--config",
        "-c",
        help="a config file to store default args values.",
        caption="Файл конфигурации",
        advanced=True,
        argtype="filename",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="%(prog)s " + __version__,
        hide=True
    )
    subparsers = parser.add_subparsers(dest="action")

    cmdparse = subparsers.add_parser("parse")
    cmdparse.add_argument(
        "filename",
        help="file to parse.",
        nargs="?",
        caption="Имя файла",
        filetypes=[("chgksuite parsable files", ("*.docx", "*.txt"))],
    )
    cmdparse.add_argument(
        "--defaultauthor",
        action="store_true",
        help="pick default author from filename " "where author is missing.",
        advanced=True,
        caption="Дописать отсутствующего автора из имени файла",
    )
    cmdparse.add_argument(
        "--encoding",
        default=None,
        help="Encoding of text file " "(use if auto-detect fails).",
        advanced=True,
        caption="Кодировка",
    )
    cmdparse.add_argument(
        "--regexes",
        default=None,
        help="A file containing regexes " "(the default is regexes.json).",
        advanced=True,
        caption="Файл с регулярными выражениями",
    )
    cmdparse.add_argument(
        "--parsedir",
        action="store_true",
        help="parse directory instead of file.",
        advanced=True,
        hide=True,
    )
    cmdparse.add_argument(
        "--links",
        default="unwrap",
        choices=["unwrap", "old"],
        help="hyperlinks handling strategy. "
        "Unwrap just leaves links as presented in the text, unchanged. "
        "Old is behaviour from versions up to v0.5.3: "
        "replace link with its href value.",
        advanced=True,
        caption="Стратегия обработки ссылок",
    )
    cmdparse.add_argument(
        "--fix_spans",
        action="store_true",
        help="try to unwrap all <span> tags. "
        "Can help fix weird Word formatting.",
        advanced=True,
        caption="Fix <span> tags",
    )
    cmdparse.add_argument(
        "--bs_prettify",
        action="store_true",
        help="old html processing behaviour (before v0.5.5). "
        "Sometimes it will yield better results than the new default.",
        advanced=True,
        caption="BeautifulSoup prettify",
    )

    cmdcompose = subparsers.add_parser("compose")
    cmdcompose.add_argument(
        "--merge",
        action="store_true",
        help="merge several source files before output.",
        advanced=True,
        hide=True,
    )
    cmdcompose.add_argument(
        "--nots",
        action="store_true",
        help="don't append timestamp to filenames",
        caption="Не добавлять временную отметку в имя файла",
        advanced=True,
    )
    cmdcompose_filetype = cmdcompose.add_subparsers(dest="filetype")
    cmdcompose_docx = cmdcompose_filetype.add_parser("docx")
    cmdcompose_docx.add_argument(
        "--docx_template",
        help="a DocX template file.",
        advanced=True,
        caption="Файл-образец",
        argtype="filename",
    )
    cmdcompose_docx.add_argument(
        "filename",
        nargs="*",
        help="file(s) to compose from.",
        caption="Имя 4s-файла",
        filetypes=[("chgksuite markup files", "*.4s")],
    )
    cmdcompose_docx.add_argument(
        "--nospoilers",
        "-n",
        action="store_true",
        help="do not whiten (spoiler) answers.",
        caption="Не забелять ответы",
    )
    cmdcompose_docx.add_argument(
        "--noanswers",
        action="store_true",
        help="do not print answers " "(not even spoilered).",
        caption="Без ответов",
    )
    cmdcompose_docx.add_argument(
        "--noparagraph",
        action="store_true",
        help="disable paragraph break " "after 'Question N.'",
        advanced=True,
        caption='Без переноса строки после "Вопрос N."',
    )
    cmdcompose_docx.add_argument(
        "--randomize",
        action="store_true",
        help="randomize order of questions.",
        advanced=True,
        caption="Перемешать вопросы",
    )
    cmdcompose_docx.add_argument(
        "--no_line_break",
        action="store_true",
        help="no line break between question and answer.",
        caption="Один перенос строки перед ответом вместо двух",
    )
    cmdcompose_docx.add_argument(
        "--one_line_break",
        action="store_true",
        help="one line break after question instead of two.",
        caption="Один перенос строки после вопроса вместо двух",
    )

    cmdcompose_tex = cmdcompose_filetype.add_parser("tex")
    cmdcompose_tex.add_argument(
        "--tex_header",
        help="a LaTeX header file.",
        caption="Файл с заголовками",
        advanced=True,
        argtype="filename",
    )
    cmdcompose_tex.add_argument(
        "filename",
        nargs="*",
        help="file(s) to compose from.",
        caption="Имя 4s-файла",
        filetypes=[("chgksuite markup files", "*.4s")],
    )
    cmdcompose_tex.add_argument(
        "--rawtex",
        action="store_true",
        advanced=True,
        caption="Не удалять исходный tex",
    )

    cmdcompose_lj = cmdcompose_filetype.add_parser("lj")
    cmdcompose_lj.add_argument(
        "filename",
        nargs="*",
        help="file(s) to compose from.",
        caption="Имя 4s-файла",
        filetypes=[("chgksuite markup files", "*.4s")],
    )
    cmdcompose_lj.add_argument(
        "--nospoilers",
        "-n",
        action="store_true",
        help="disable spoilers.",
        caption="Отключить спойлер-теги",
    )
    cmdcompose_lj.add_argument(
        "--splittours",
        action="store_true",
        help="make a separate post for each tour.",
        caption="Разбить на туры",
    )
    cmdcompose_lj.add_argument(
        "--genimp",
        action="store_true",
        help="make a 'general impressions' post.",
        caption="Пост с общими впечатлениями",
    )
    cmdcompose_lj.add_argument(
        "--navigation",
        action="store_true",
        help="add navigation to posts.",
        caption="Добавить навигацию к постам",
    )
    cmdcompose_lj.add_argument(
        "--login", "-l", help="livejournal login", caption="ЖЖ-логин"
    )
    cmdcompose_lj.add_argument(
        "--password", "-p", help="livejournal password", caption="Пароль от ЖЖ"
    )
    cmdcompose_lj.add_argument(
        "--community",
        "-c",
        help="livejournal community to post to.",
        caption="ЖЖ-сообщество",
    )
    cmdcompose_lj.add_argument(
        "--security",
        help="set to 'friends' to make post friends-only, else specify allowmask.",
        caption="Указание группы друзей (или 'friends' для всех друзей)",
    )
    cmdcompose_base = cmdcompose_filetype.add_parser("base")
    cmdcompose_base.add_argument(
        "filename",
        nargs="*",
        help="file(s) to compose from.",
        caption="Имя 4s-файла",
        filetypes=[("chgksuite markup files", "*.4s")],
    )
    cmdcompose_base.add_argument("--clipboard", action="store_true")
    cmdcompose_redditmd = cmdcompose_filetype.add_parser("redditmd")
    cmdcompose_redditmd.add_argument(
        "filename",
        nargs="*",
        help="file(s) to compose from.",
        caption="Имя 4s-файла",
        filetypes=[("chgksuite markup files", "*.4s")],
    )
    cmdcompose_pptx = cmdcompose_filetype.add_parser("pptx")
    cmdcompose_pptx.add_argument(
        "filename",
        nargs="*",
        help="file(s) to compose from.",
        caption="Имя 4s-файла",
        filetypes=[("chgksuite markup files", "*.4s")],
    )
    cmdcompose_pptx.add_argument(
        "--pptx_template",
        help="a pptx template file.",
        advanced=True,
        caption="Файл-образец",
        argtype="filename",
    )
    cmdcompose_pptx.add_argument(
        "--addcomment",
        help="add comment to answer page.",
        action="store_true",
        advanced=True,
        caption="Добавить комментарии к ответам",
    )
    cmdcompose_pptx.add_argument(
        "--addplug",
        help="add blank slide between question and answer.",
        action="store_true",
        advanced=True,
        caption="Добавлять слайд-заглушку перед ответом",
    )

    cmdtrello = subparsers.add_parser("trello")
    cmdtrello_subcommands = cmdtrello.add_subparsers(dest="trellosubcommand")
    cmdtrello_download = cmdtrello_subcommands.add_parser(
        "download", caption="Скачать из Трелло"
    )
    cmdtrello_download.add_argument(
        "folder",
        help="path to the folder" "to synchronize with a trello board.",
        caption="Папка",
    )
    cmdtrello_download.add_argument(
        "--si",
        action="store_true",
        help="This flag includes card captions "
        "in .4s files. "
        "Useful for editing SI "
        "files (rather than CHGK)",
        caption="Формат Своей игры",
    )
    cmdtrello_download.add_argument(
        "--onlyanswers",
        action="store_true",
        help="This flag forces SI download to only include answers.",
        caption="Только ответы",
    )
    cmdtrello_download.add_argument(
        "--noanswers",
        action="store_true",
        help="This flag forces SI download to not include answers.",
        caption="Без ответов",
    )
    cmdtrello_download.add_argument(
        "--singlefile",
        action="store_true",
        help="This flag forces SI download all themes to single file.",
        caption="Склеить всё в один файл",
    )
    cmdtrello_download.add_argument(
        "--qb",
        action="store_true",
        help="Quizbowl format",
        caption="Формат квизбола",
    )
    cmdtrello_download.add_argument(
        "--labels",
        action="store_true",
        help="Use this if you also want " "to have lists based on labels.",
        caption="Создать файлы из лейблов Трелло",
    )

    cmdtrello_upload = cmdtrello_subcommands.add_parser(
        "upload", caption="Загрузить в Трелло"
    )
    cmdtrello_upload.add_argument(
        "board_id", help="trello board id.", caption="ID доски"
    )
    cmdtrello_upload.add_argument(
        "filename",
        nargs="*",
        help="file(s) to upload to trello.",
        caption="Имя 4s-файла",
    )
    cmdtrello_upload.add_argument(
        "--author",
        action="store_true",
        help="Display authors in cards' captions",
        caption="Дописать авторов в заголовок карточки",
    )

    cmdtrello_subcommands.add_parser("token")

    args = parser.parse_args()

    if not args.regexes:
        args.regexes = os.path.join(resourcedir, "regexes.json")
    if not args.docx_template:
        args.docx_template = os.path.join(resourcedir, "template.docx")
    if not args.tex_header:
        args.tex_header = os.path.join(resourcedir, "cheader.tex")
    if args.config:
        with open(args.config, "r") as f:
            config = json.load(f)
        for key in config:
            if not isinstance(config[key], basestring):
                val = config[key]
            elif os.path.isfile(config[key]):
                val = os.path.abspath(config[key])
            elif os.path.isfile(
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), config[key]
                )
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
