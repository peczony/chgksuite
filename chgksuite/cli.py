#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import argparse
import json
import os

from chgksuite.common import (
    DefaultNamespace,
    get_source_dirs,
    load_settings,
)
from chgksuite.composer import gui_compose
from chgksuite.handouter.runner import gui_handouter
from chgksuite.handouter.tex_internals import GREYTEXT_LANGS
from chgksuite.parser import gui_parse
from chgksuite.trello import gui_trello
from chgksuite.version import __version__

LANGS = ["by", "by_tar", "en", "kz_cyr", "ru", "sr", "ua", "uz", "uz_cyr"] + ["custom"]

debug = False


class ArgparseBuilder:
    def __init__(self, parser, use_wrapper):
        self.parser = parser
        self.use_wrapper = use_wrapper

    def apply_func(self, parser, func, *args, **kwargs):
        if self.use_wrapper:
            return getattr(parser, func)(*args, **kwargs)
        else:
            for k in ("caption", "advanced", "argtype", "hide", "filetypes"):
                try:
                    kwargs.pop(k)
                except KeyError:
                    pass
            return getattr(parser, func)(*args, **kwargs)

    def add_argument(self, parser, *args, **kwargs):
        return self.apply_func(parser, "add_argument", *args, **kwargs)

    def add_parser(self, parser, *args, **kwargs):
        return self.apply_func(parser, "add_parser", *args, **kwargs)

    def get_default_overrides(self):
        settings = load_settings()
        default_overrides = settings.get("default_overrides") or {}
        assert isinstance(default_overrides, dict)
        return default_overrides

    def build(self):
        parser = self.parser
        default_overrides = self.get_default_overrides()
        self.add_argument(
            parser,
            "--debug",
            "-d",
            action="store_true",
            help="Print and save some debug info.",
            caption="Отладочная информация",
            advanced=True,
        )
        self.add_argument(
            parser,
            "--config",
            "-c",
            help="a config file to store default args values.",
            caption="Файл конфигурации",
            advanced=True,
            argtype="filename",
        )
        self.add_argument(
            parser,
            "-v",
            "--version",
            action="version",
            version="%(prog)s " + __version__,
            hide=True,
        )
        subparsers = parser.add_subparsers(dest="action")

        cmdparse = subparsers.add_parser("parse")
        self.add_argument(
            cmdparse,
            "filename",
            help="file to parse.",
            nargs="?",
            caption="Имя файла",
            filetypes=[("chgksuite parsable files", ("*.docx", "*.txt"))],
        )
        self.add_argument(
            cmdparse,
            "--language",
            "-lang",
            help="language to use while parsing.",
            choices=LANGS,
            default=default_overrides.get("language") or "ru",
            caption="Язык",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--labels_file",
            help="i18n config",
            caption="Конфиг для интернационализации",
            advanced=True,
            argtype="filename",
        )
        self.add_argument(
            cmdparse,
            "--defaultauthor",
            default="off",
            help="pick default author where author is missing. 'off' is default, 'file' is from filename, you can add custom value",
            advanced=True,
            caption="Дописать отсутствующего автора. 'off' — дефолт, 'file' — взять из имени файла, вы также можете указать свою строчку",
        )
        self.add_argument(
            cmdparse,
            "--preserve_formatting",
            "-pf",
            action="store_true",
            help="Preserve bold and italic.",
            caption="Сохранять полужирный и курсив",
            advanced=True,
        )
        self.add_argument(
            cmdparse,
            "--encoding",
            default=default_overrides.get("encoding") or None,
            help="Encoding of text file (use if auto-detect fails).",
            advanced=True,
            caption="Кодировка",
        )
        self.add_argument(
            cmdparse,
            "--regexes",
            default=default_overrides.get("encoding") or None,
            help="A file containing regexes (the default is regexes_ru.json).",
            advanced=True,
            caption="Файл с регулярными выражениями",
            argtype="filename",
        )
        self.add_argument(
            cmdparse,
            "--parsedir",
            action="store_true",
            help="parse directory instead of file.",
            advanced=True,
            hide=True,
        )
        self.add_argument(
            cmdparse,
            "--links",
            default=default_overrides.get("links") or "unwrap",
            choices=["unwrap", "old"],
            help="hyperlinks handling strategy. "
            "Unwrap just leaves links as presented in the text, unchanged. "
            "Old is behaviour from versions up to v0.5.3: "
            "replace link with its href value.",
            advanced=True,
            caption="Стратегия обработки ссылок",
        )
        self.add_argument(
            cmdparse,
            "--fix_spans",
            action="store_true",
            help="try to unwrap all <span> tags. Can help fix weird Word formatting.",
            advanced=True,
            caption="Fix <span> tags",
        )
        self.add_argument(
            cmdparse,
            "--no_image_prefix",
            action="store_true",
            help="don't make image prefix from filename",
            advanced=True,
            caption="Don't make image prefix from filename",
        )
        self.add_argument(
            cmdparse,
            "--parsing_engine",
            choices=[
                "pypandoc",
                "pypandoc_html",
                "mammoth_bs_hard_unwrap",
                "mammoth",
            ],
            default=default_overrides.get("parsing_engine") or "mammoth",
            help="old html processing behaviour (before v0.5.5). "
            "Sometimes it will yield better results than the new default.",
            advanced=True,
            caption="HTML parsing engine",
        )
        self.add_argument(
            cmdparse,
            "--numbers_handling",
            default=default_overrides.get("numbers_handling") or "default",
            choices=["default", "all", "none"],
            help="question numbers handling strategy. "
            "Default preserves zero questions and numbering "
            "if the first question has number > 1, omits number otherwise. "
            "All preserves all numbers, none omits all numbers "
            "(was default behaviour pre-0.8.0.)",
            advanced=True,
            caption="Стратегия обработки номеров вопросов",
        )
        self.add_argument(
            cmdparse,
            "--typography_quotes",
            default=default_overrides.get("typography_quotes") or "on",
            choices=["smart", "on", "off"],
            help="typography: try to fix quotes.",
            advanced=True,
            caption="Типография: кавычки",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--typography_dashes",
            default=default_overrides.get("typography_dashes") or "on",
            choices=["smart", "on", "off"],
            help="typography: try to fix dashes.",
            advanced=True,
            caption="Типография: тире",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--typography_whitespace",
            default=default_overrides.get("typography_whitespace") or "on",
            choices=["on", "off"],
            help="typography: try to fix whitespace.",
            advanced=True,
            caption="Типография: whitespace",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--typography_accents",
            default=default_overrides.get("typography_accents") or "on",
            choices=["smart", "light", "on", "off"],
            help="typography: try to fix accents.",
            advanced=True,
            caption="Типография: ударения",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--typography_percent",
            default=default_overrides.get("typography_percent") or "on",
            choices=["on", "off"],
            help="typography: try to fix percent encoding.",
            advanced=True,
            caption="Типография: %-энкодинг ссылок",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--single_number_line_handling",
            default=default_overrides.get("single_number_line_handling") or "smart",
            choices=["smart", "on", "off"],
            help="handling cases where a line consists of a single number.",
            advanced=True,
            caption="Обработка строчек, состоящих из одного числа",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--tour_numbers_as_words",
            choices=["on", "off"],
            default=default_overrides.get("tour_numbers_as_words") or "off",
            help="force tour numbers as words",
            caption="Номера туров словами",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--download_images",
            action="store_true",
            help="download images from direct URLs and replace with local references",
            caption="Скачивать изображения по прямым ссылкам",
            advanced=True,
        )
        self.add_argument(
            cmdparse,
            "--add_ts",
            "-ts",
            choices=["on", "off"],
            default=default_overrides.get("add_ts") or "off",
            help="append timestamp to filenames",
            caption="Добавить временную отметку в имя файла",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--replace_no_break_spaces",
            choices=["on", "off"],
            default=default_overrides.get("replace_no_break_spaces") or "on",
            help="add non-breaking spaces where applicable",
            caption="Добавить неразрывные пробелы",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdparse,
            "--replace_no_break_hyphens",
            choices=["on", "off"],
            default=default_overrides.get("replace_no_break_hyphens") or "on",
            help="add non-breaking hyphens where applicable",
            caption="Добавить неразрывные дефисы",
            advanced=True,
            argtype="radiobutton",
        )

        cmdcompose = subparsers.add_parser("compose")
        self.add_argument(
            cmdcompose,
            "--merge",
            action="store_true",
            help="merge several source files before output.",
            advanced=True,
            hide=True,
        )
        self.add_argument(
            cmdcompose,
            "--language",
            "-lang",
            help="language to use while composing.",
            choices=LANGS,
            default=default_overrides.get("language") or "ru",
            caption="Язык",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdcompose,
            "--labels_file",
            help="i18n config",
            caption="Конфиг для интернационализации",
            advanced=True,
            argtype="filename",
        )
        self.add_argument(
            cmdcompose,
            "--imgur_client_id",
            default=default_overrides.get("imgur_client_id") or None,
            help="imgur client id",
            caption="Client ID для API Imgur",
            advanced=True,
        )
        self.add_argument(
            cmdcompose,
            "--add_ts",
            "-ts",
            choices=["on", "off"],
            default=default_overrides.get("add_ts") or "off",
            help="append timestamp to filenames",
            caption="Добавить временную отметку в имя файла",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdcompose,
            "--replace_no_break_spaces",
            choices=["on", "off"],
            default=default_overrides.get("replace_no_break_spaces") or "on",
            help="add non-breaking spaces where applicable",
            caption="Добавить неразрывные пробелы",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdcompose,
            "--replace_no_break_hyphens",
            choices=["on", "off"],
            default=default_overrides.get("replace_no_break_hyphens") or "on",
            help="add non-breaking hyphens where applicable",
            caption="Добавить неразрывные дефисы",
            advanced=True,
            argtype="radiobutton",
        )
        cmdcompose_filetype = cmdcompose.add_subparsers(dest="filetype")
        cmdcompose_docx = cmdcompose_filetype.add_parser("docx")
        self.add_argument(
            cmdcompose_docx,
            "--docx_template",
            help="a DocX template file.",
            advanced=True,
            caption="Файл-образец",
            argtype="filename",
        )
        self.add_argument(
            cmdcompose_docx,
            "--font_face",
            default=default_overrides.get("font_face") or None,
            help="font face to use in the document.",
            advanced=True,
            caption="Шрифт",
        )
        self.add_argument(
            cmdcompose_docx,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        self.add_argument(
            cmdcompose_docx,
            "--spoilers",
            "-s",
            choices=["off", "whiten", "pagebreak", "dots"],
            default=default_overrides.get("spoilers") or "off",
            help="whether to hide answers behind spoilers.",
            caption="Спойлеры",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdcompose_docx,
            "--screen_mode",
            "-sm",
            choices=["off", "replace_all", "add_versions", "add_versions_columns"],
            default=default_overrides.get("screen_mode") or "off",
            help="exporting questions for screen.",
            caption="Экспорт для экрана",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdcompose_docx,
            "--noanswers",
            action="store_true",
            help="do not print answers (not even spoilered).",
            caption="Без ответов",
        )
        self.add_argument(
            cmdcompose_docx,
            "--noparagraph",
            action="store_true",
            help="disable paragraph break after 'Question N.'",
            advanced=True,
            caption='Без переноса строки после "Вопрос N."',
        )

        self.add_argument(
            cmdcompose_docx,
            "--only_question_number",
            action="store_true",
            help="only show question number",
            advanced=True,
            caption='Без слова "Вопрос" в "Вопрос N."',
        )
        self.add_argument(
            cmdcompose_docx,
            "--randomize",
            action="store_true",
            help="randomize order of questions.",
            advanced=True,
            caption="Перемешать вопросы",
        )
        self.add_argument(
            cmdcompose_docx,
            "--no_line_break",
            action="store_true",
            help="no line break between question and answer.",
            caption="Один перенос строки перед ответом вместо двух",
        )
        self.add_argument(
            cmdcompose_docx,
            "--one_line_break",
            action="store_true",
            help="one line break after question instead of two.",
            caption="Один перенос строки после вопроса вместо двух",
        )

        cmdcompose_tex = cmdcompose_filetype.add_parser("tex")
        self.add_argument(
            cmdcompose_tex,
            "--tex_header",
            help="a LaTeX header file.",
            caption="Файл с заголовками",
            advanced=True,
            argtype="filename",
        )
        self.add_argument(
            cmdcompose_tex,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        self.add_argument(
            cmdcompose_tex,
            "--rawtex",
            action="store_true",
            advanced=True,
            caption="Не удалять исходный tex",
        )

        cmdcompose_lj = cmdcompose_filetype.add_parser("lj")
        self.add_argument(
            cmdcompose_lj,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        self.add_argument(
            cmdcompose_lj,
            "--nospoilers",
            "-n",
            action="store_true",
            help="disable spoilers.",
            caption="Отключить спойлер-теги",
        )
        self.add_argument(
            cmdcompose_lj,
            "--splittours",
            action="store_true",
            help="make a separate post for each tour.",
            caption="Разбить на туры",
        )
        self.add_argument(
            cmdcompose_lj,
            "--genimp",
            action="store_true",
            help="make a 'general impressions' post.",
            caption="Пост с общими впечатлениями",
        )
        self.add_argument(
            cmdcompose_lj,
            "--navigation",
            action="store_true",
            help="add navigation to posts.",
            caption="Добавить навигацию к постам",
        )
        self.add_argument(
            cmdcompose_lj, "--login", "-l", help="livejournal login", caption="ЖЖ-логин"
        )
        self.add_argument(
            cmdcompose_lj,
            "--password",
            "-p",
            help="livejournal password",
            caption="Пароль от ЖЖ",
        )
        self.add_argument(
            cmdcompose_lj,
            "--community",
            "-c",
            help="livejournal community to post to.",
            caption="ЖЖ-сообщество",
        )
        self.add_argument(
            cmdcompose_lj,
            "--security",
            help="set to 'friends' to make post friends-only, else specify allowmask.",
            caption="Указание группы друзей (или 'friends' для всех друзей)",
        )
        cmdcompose_base = cmdcompose_filetype.add_parser("base")
        self.add_argument(
            cmdcompose_base,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        self.add_argument(
            cmdcompose_base,
            "--remove_accents",
            action="store_true",
            caption="Убрать знаки ударения",
            help="remove combining acute accents to prevent db.chgk.info search breaking",
        )
        self.add_argument(
            cmdcompose_base,
            "--clipboard",
            caption="Скопировать результат в буфер",
            help="copy result to clipboard",
            action="store_true",
        )
        cmdcompose_redditmd = cmdcompose_filetype.add_parser("redditmd")
        self.add_argument(
            cmdcompose_redditmd,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        cmdcompose_pptx = cmdcompose_filetype.add_parser("pptx")
        self.add_argument(
            cmdcompose_pptx,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        self.add_argument(
            cmdcompose_pptx,
            "--disable_numbers",
            help="do not put question numbers on slides.",
            advanced=False,
            caption="Не добавлять номера вопросов",
            action="store_true",
        )
        self.add_argument(
            cmdcompose_pptx,
            "--pptx_config",
            help="a pptx config file.",
            advanced=True,
            caption="Файл конфигурации",
            argtype="filename",
        )
        self.add_argument(
            cmdcompose_pptx,
            "--do_dot_remove_accents",
            help="do not remove accents.",
            advanced=True,
            caption="Не убирать знаки ударения",
            action="store_true",
        )
        cmdcompose_telegram = cmdcompose_filetype.add_parser("telegram")
        self.add_argument(
            cmdcompose_telegram,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        self.add_argument(
            cmdcompose_telegram,
            "--tgaccount",
            default=default_overrides.get("tgaccount") or "my_account",
            help="a made-up string designating account to use.",
            caption="Аккаунт для постинга",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--tgchannel",
            required=True,
            help="a channel to post questions to.",
            caption="Название канала, в который постим",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--tgchat",
            required=True,
            help="a chat connected to the channel.",
            caption="Название чата, привязанного к каналу",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--dry_run",
            advanced=True,
            action="store_true",
            help="don't try to post.",
            caption="Тестовый прогон (не постить в телеграм, только подключиться)",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--reset_api",
            advanced=True,
            action="store_true",
            help="reset api_id/api_hash.",
            caption="Сбросить api_id/api_hash",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--no_hide_password",
            advanced=True,
            action="store_true",
            help="don't hide 2FA password.",
            caption="Не скрывать пароль 2FA при вводе (включите, если в вашем терминале есть проблемы со вводом пароля)",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--nospoilers",
            "-n",
            action="store_true",
            help="do not whiten (spoiler) answers.",
            caption="Не закрывать ответы спойлером",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--skip_until",
            type=int,
            help="skip questions until N.",
            caption="Начать выкладывать с N-го вопроса",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--disable_asterisks_processing",
            type=int,
            help="disable asterisks processing.",
            caption="Не обрабатывать звёздочки",
        )
        cmdcompose_add_stats = cmdcompose_filetype.add_parser("add_stats")
        self.add_argument(
            cmdcompose_add_stats,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )
        self.add_argument(
            cmdcompose_add_stats,
            "--rating_ids",
            "-r",
            help="tournament id (comma-separated in case of sync+async parts).",
            caption="id турнира (через запятую для синхрона+асинхрона)",
        )
        self.add_argument(
            cmdcompose_add_stats,
            "--custom_csv",
            help="custom csv/xlsx in rating.chgk.info format",
            caption="кастомный csv/xlsx с результатами в формате rating.chgk.info",
            argtype="filename",
        )
        self.add_argument(
            cmdcompose_add_stats,
            "--custom_csv_args",
            help="""custom csv arguments in json format (e.g. {"delimiter": ";"})""",
            default="{}",
            caption="""кастомные параметры для импорта csv (например, {"delimiter": ";"})""",
            advanced=True,
        )
        self.add_argument(
            cmdcompose_add_stats,
            "--question_range",
            help="range of question numbers to include.",
            caption='Диапазон вопросов (например, "25-36"), по умолчанию берутся все)',
        )
        self.add_argument(
            cmdcompose_add_stats,
            "--team_naming_threshold",
            "-tnt",
            type=int,
            default=default_overrides.get("team_naming_threshold") or 2,
            help="threshold for naming teams who scored at the question.",
            caption="Граница вывода названий команд",
        )
        cmdcompose_openquiz = cmdcompose_filetype.add_parser("openquiz")
        self.add_argument(
            cmdcompose_openquiz,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", "*.4s")],
        )

        cmdtrello = subparsers.add_parser("trello")
        cmdtrello_subcommands = cmdtrello.add_subparsers(dest="trellosubcommand")
        cmdtrello_download = self.add_parser(
            cmdtrello_subcommands, "download", caption="Скачать из Трелло"
        )
        self.add_argument(
            cmdtrello_download,
            "folder",
            help="path to the folderto synchronize with a trello board.",
            caption="Папка",
        )
        self.add_argument(
            cmdtrello_download,
            "--lists",
            help="Download only specified lists.",
            caption="Скачать только указанные списки (через запятую)",
        )
        self.add_argument(
            cmdtrello_download,
            "--si",
            action="store_true",
            help="This flag includes card captions "
            "in .4s files. "
            "Useful for editing SI "
            "files (rather than CHGK)",
            caption="Формат Своей игры",
        )
        self.add_argument(
            cmdtrello_download,
            "--replace_double_line_breaks",
            "-rd",
            action="store_true",
            help="This flag replaces double line breaks with single ones.",
            caption="Убрать двойные переносы строк",
        )
        self.add_argument(
            cmdtrello_download,
            "--fix_trello_new_editor",
            "-ftne",
            choices=["on", "off"],
            default=default_overrides.get("fix_trello_new_editor") or "on",
            help="This flag fixes mess caused by Trello's new editor "
            "(introduced in early 2023).",
            caption="Пофиксить новый редактор Трелло",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdtrello_download,
            "--onlyanswers",
            action="store_true",
            help="This flag forces SI download to only include answers.",
            caption="Только ответы",
        )
        self.add_argument(
            cmdtrello_download,
            "--noanswers",
            action="store_true",
            help="This flag forces SI download to not include answers.",
            caption="Без ответов",
        )
        self.add_argument(
            cmdtrello_download,
            "--singlefile",
            action="store_true",
            help="This flag forces SI download all themes to single file.",
            caption="Склеить всё в один файл",
        )
        self.add_argument(
            cmdtrello_download,
            "--qb",
            action="store_true",
            help="Quizbowl format",
            caption="Формат квизбола",
        )
        self.add_argument(
            cmdtrello_download,
            "--labels",
            action="store_true",
            help="Use this if you also want to have lists based on labels.",
            caption="Создать файлы из лейблов Трелло",
        )

        cmdtrello_upload = self.add_parser(
            cmdtrello_subcommands, "upload", caption="Загрузить в Трелло"
        )
        self.add_argument(
            cmdtrello_upload, "board_id", help="trello board id.", caption="ID доски"
        )
        self.add_argument(
            cmdtrello_upload,
            "filename",
            nargs="*",
            help="file(s) to upload to trello.",
            caption="Имя 4s-файла",
        )
        self.add_argument(
            cmdtrello_upload,
            "--author",
            action="store_true",
            help="Display authors in cards' captions",
            caption="Дописать авторов в заголовок карточки",
        )
        self.add_argument(
            cmdtrello_upload,
            "--list_name",
            help="List name where to upload cards",
            caption="Имя списка для загрузки карточек",
        )

        cmdtrello_token = cmdtrello_subcommands.add_parser("token")
        self.add_argument(
            cmdtrello_token,
            "--no-browser",
            action="store_true",
            help="Don't try to open in browser",
            caption="Не открывать браузер",
        )

        cmdhandouts = subparsers.add_parser("handouts")
        cmdhandouts_subcommands = cmdhandouts.add_subparsers(dest="handoutssubcommand")
        cmdhandouts_run = self.add_parser(cmdhandouts_subcommands, "run")
        self.add_argument(
            cmdhandouts_run,
            "filename",
            help="file with handouts",
            caption="Имя файла с раздатками",
            filetypes=[("handouts files", "*.hndts"), ("text files", "*.txt")],
        )
        self.add_argument(
            cmdhandouts_run,
            "--lang",
            default="ru",
            argtype="radiobutton",
            choices=sorted(GREYTEXT_LANGS.keys()),
            help="language",
            caption="Язык",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--compress",
            action="store_true",
            help="compress",
            caption="Сжать файл после вёрстки (требует установленного ghostscript)",
            advanced=True,
        )
        self.add_argument(cmdhandouts_run, "--font", "-f", help="font", caption="Шрифт")
        self.add_argument(
            cmdhandouts_run,
            "--font_size",
            type=int,
            default=14,
            help="font size",
            caption="Размер шрифта",
        )
        self.add_argument(
            cmdhandouts_run,
            "--pdfsettings",
            choices=["screen", "ebook", "printer", "prepress", "default"],
            default="default",
            advanced=True,
            caption="Настройки pdfsettings для ghostscript",
        )
        self.add_argument(
            cmdhandouts_run,
            "--paperwidth",
            type=float,
            default=210,
            help="paper width",
            caption="Ширина бумаги",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--paperheight",
            type=float,
            default=297,
            help="paper height",
            caption="Высота бумаги",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--margin_top",
            type=float,
            default=5,
            help="top margin",
            caption="Верхний отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--margin_bottom",
            type=float,
            default=5,
            help="bottom margin",
            caption="Нижний отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--margin_left",
            type=float,
            default=5,
            help="left margin",
            caption="Левый отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--margin_right",
            type=float,
            default=5,
            help="right margin",
            caption="Правый отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--boxwidth",
            type=float,
            help="box width",
            caption="Ширина блока",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--boxwidthinner",
            type=float,
            help="box width inner",
            caption="Внутренняя ширина блока",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--tikz_mm",
            type=float,
            default=2,
            help="tikz_mm width",
            caption="Ширина tikz_mm",
            advanced=True,
        )

        cmdhandouts_generate = self.add_parser(cmdhandouts_subcommands, "generate")
        self.add_argument(
            cmdhandouts_generate,
            "filename",
            help="file with questions packet",
            caption="Имя файла с пакетом",
            filetypes=[("chgksuite files", "*.4s")],
        )
        self.add_argument(
            cmdhandouts_generate,
            "--lang",
            default="ru",
            help="language",
            caption="Язык",
            argtype="radiobutton",
            choices=sorted(GREYTEXT_LANGS.keys()),
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_generate,
            "--separate",
            action="store_true",
            help="Generate separate handouts for each question",
            caption="Сгенерировать отдельный файл с раздатками для каждого вопроса",
        )
        self.add_argument(
            cmdhandouts_generate,
            "--list-handouts",
            "-l",
            action="store_true",
            help="Generate a file with a list of handouts",
            caption="Сгенерировать файл со списком раздаток",
        )

        cmdhandouts_pack = self.add_parser(cmdhandouts_subcommands, "pack")
        self.add_argument(
            cmdhandouts_pack,
            "folder",
            help="input directory",
            caption="Папка с раздатками",
        )
        self.add_argument(
            cmdhandouts_pack,
            "--output_filename_prefix",
            "-o",
            default="packed_handouts",
            help="output filename prefix",
            caption="Префикс имени выходного файла",
        )
        self.add_argument(
            cmdhandouts_pack,
            "--n_teams",
            "-n",
            type=int,
            required=True,
            help="number of teams",
            caption="Количество команд",
        )
        self.add_argument(
            cmdhandouts_pack,
            "--font",
            "-f",
            help="font",
            caption="Шрифт",
        )

        cmdhandouts_install = self.add_parser(cmdhandouts_subcommands, "install")
        self.add_argument(
            cmdhandouts_install,
            "--tectonic_package_regex",
            advanced=True,
            caption="Переопределить имя файла с релизом tectonic",
        )


def single_action(args, use_wrapper, resourcedir):
    if use_wrapper:
        args.console_mode = False
    else:
        args.console_mode = True

    if args.language in LANGS:
        if args.action == "parse":
            regex_lang = "by" if args.language == "by_tar" else args.language
            args.regexes = os.path.join(resourcedir, f"regexes_{regex_lang}.json")
        args.labels_file = os.path.join(resourcedir, f"labels_{args.language}.toml")
    if not args.docx_template:
        args.docx_template = os.path.join(resourcedir, "template.docx")
    if not args.pptx_config:
        args.pptx_config = os.path.join(resourcedir, "pptx_config.toml")
    if not args.tex_header:
        args.tex_header = os.path.join(resourcedir, "cheader.tex")
    if args.config:
        with open(args.config, "r") as f:
            config = json.load(f)
        for key in config:
            if not isinstance(config[key], str):
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
    if args.action == "parse":
        gui_parse(args)
    if args.action == "compose":
        gui_compose(args)
    if args.action == "trello":
        gui_trello(args)
    if args.action == "handouts":
        gui_handouter(args)


def app():
    _, resourcedir = get_source_dirs()
    parser = argparse.ArgumentParser(prog="chgksuite")
    ArgparseBuilder(parser, False).build()
    args = DefaultNamespace(parser.parse_args())
    single_action(args, False, resourcedir)
