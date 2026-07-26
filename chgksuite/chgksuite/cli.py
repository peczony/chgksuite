#!/usr/bin/env python

import argparse
import json
import os
from pathlib import Path

from chgksuite.board import gui_board
from chgksuite.common import (
    DefaultNamespace,
    get_source_dirs,
    load_settings,
)
from chgksuite.composer import gui_compose
from chgksuite.composer.composer_common import ext_to_game
from chgksuite.composer.telegram import get_saved_telegram_targets
from chgksuite.handouter.runner import gui_handouter
from chgksuite.parser import gui_parse
from chgksuite.version import __version__

LANGS = ["az", "by", "by_tar", "en", "kz_cyr", "ru", "sr", "ua", "uz", "uz_cyr"] + [
    "custom"
]
HANDOUT_LANGS = [lang for lang in LANGS if lang != "custom"]

debug = False


class ArgparseBuilder:
    def __init__(self, parser, use_wrapper):
        self.parser = parser
        self.use_wrapper = use_wrapper

    def apply_func(self, parser, func, *args, **kwargs):
        if self.use_wrapper:
            return getattr(parser, func)(*args, **kwargs)
        else:
            for k in (
                "caption",
                "advanced",
                "argtype",
                "hide",
                "filetypes",
                "combobox_values",
            ):
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
            "--game",
            choices=["chgk", "brain", "si", "troika"],
            default="chgk",
            help="game format: chgk (default), brain, si, or troika.",
            caption="Формат игры",
            argtype="radiobutton",
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
            argtype="radiobutton",
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
                "python_docx",
                "pypandoc",
                "pypandoc_html",
                "mammoth_bs_hard_unwrap",
                "mammoth",
            ],
            default=default_overrides.get("parsing_engine") or "python_docx",
            help="DOCX parsing engine. python_docx uses the bundled parser and does "
            "not require pandoc; pypandoc_html keeps the previous pandoc-based path.",
            advanced=True,
            caption="DOCX parsing engine",
            argtype="radiobutton",
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
            argtype="radiobutton",
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
            "--font",
            "--font_face",
            dest="font",
            default=default_overrides.get("font")
            or default_overrides.get("font_face")
            or None,
            help="font face to use in the document.",
            advanced=True,
            caption="Шрифт",
        )
        self.add_argument(
            cmdcompose_docx,
            "--optimize_size",
            choices=["on", "off"],
            default=default_overrides.get("optimize_size") or "on",
            help="recompress images to reduce DOCX size.",
            advanced=True,
            caption="Оптимизировать размер",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdcompose_docx,
            "--smaller_source_and_author",
            choices=["on", "off"],
            default=default_overrides.get("smaller_source_and_author") or "on",
            help="set source/author fields 2pt below body size.",
            advanced=True,
            caption="Источники/авторы мельче",
            argtype="radiobutton",
        )
        self.add_argument(
            cmdcompose_docx,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
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
        self.add_argument(
            cmdcompose_docx,
            "--ignore_missing_images",
            action="store_true",
            help="insert placeholder text instead of failing when an image is not found.",
            advanced=True,
            caption="Игнорировать отсутствующие картинки",
        )

        cmdcompose_pdf = cmdcompose_filetype.add_parser("pdf")
        self.add_argument(
            cmdcompose_pdf,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
        )
        self.add_argument(
            cmdcompose_pdf,
            "--device",
            choices=["desktop", "mobile"],
            default="desktop",
            help="page size: desktop (A4) or mobile (phone-screen-sized).",
            caption="Устройство",
        )
        self.add_argument(
            cmdcompose_pdf,
            "--font",
            "--font_face",
            dest="font",
            default=default_overrides.get("font")
            or default_overrides.get("font_face")
            or None,
            help="font family to use in the document.",
            caption="Шрифт",
        )
        self.add_argument(
            cmdcompose_pdf,
            "--pdf_config",
            help="a pdf (typst) typography config file.",
            advanced=True,
            caption="Файл конфигурации",
            argtype="filename",
        )
        self.add_argument(
            cmdcompose_pdf,
            "--rawtypst",
            action="store_true",
            advanced=True,
            caption="Не удалять исходный typst",
        )
        self.add_argument(
            cmdcompose_pdf,
            "--ignore_missing_images",
            action="store_true",
            help="insert placeholder text instead of failing when an image is not found.",
            advanced=True,
            caption="Игнорировать отсутствующие картинки",
        )

        cmdcompose_lj = cmdcompose_filetype.add_parser("lj")
        self.add_argument(
            cmdcompose_lj,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
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
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
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
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
        )
        cmdcompose_markdown = cmdcompose_filetype.add_parser("markdown")
        self.add_argument(
            cmdcompose_markdown,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
        )
        cmdcompose_pptx = cmdcompose_filetype.add_parser("pptx")
        self.add_argument(
            cmdcompose_pptx,
            "filename",
            nargs="*",
            help="file(s) to compose from.",
            caption="Имя 4s-файла",
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
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
            "--font",
            default=default_overrides.get("font") or None,
            help="font face to use in the presentation.",
            advanced=True,
            caption="Шрифт",
        )
        self.add_argument(
            cmdcompose_pptx,
            "--optimize_size",
            choices=["on", "off"],
            default=default_overrides.get("optimize_size") or "on",
            help="recompress images to reduce PPTX size.",
            advanced=True,
            caption="Оптимизировать размер",
            argtype="radiobutton",
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
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
        )
        self.add_argument(
            cmdcompose_telegram,
            "--tgaccount",
            default=default_overrides.get("tgaccount") or "my_account",
            help="a made-up string designating account to use.",
            caption="Аккаунт для постинга",
        )
        saved_targets = get_saved_telegram_targets()
        self.add_argument(
            cmdcompose_telegram,
            "--tgchannel",
            required=True,
            help="a channel to post questions to.",
            caption="Название канала, в который постим",
            argtype="combobox",
            combobox_values=saved_targets,
        )
        self.add_argument(
            cmdcompose_telegram,
            "--tgchat",
            required=True,
            help="a chat connected to the channel.",
            caption="Название чата, привязанного к каналу",
            argtype="combobox",
            combobox_values=saved_targets,
        )
        self.add_argument(
            cmdcompose_telegram,
            "--resize_images",
            advanced=True,
            action="store_true",
            help="resize images to max 800px on the longest side.",
            caption="Уменьшить размер картинок до 800px по длинной стороне",
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
            "--add_polls",
            advanced=True,
            action="store_true",
            help="add polls after questions/tours/packet.",
            caption="Добавлять опросы после вопросов/туров/пакета",
        )
        self.add_argument(
            cmdcompose_telegram,
            "--poll_config",
            help="path to poll config TOML file.",
            caption="Файл конфигурации опросов",
            argtype="filename",
            advanced=True,
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
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
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
            filetypes=[("chgksuite markup files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
        )

        cmdboard = subparsers.add_parser("board", aliases=["trello"])
        cmdboard_subcommands = cmdboard.add_subparsers(dest="boardsubcommand")
        cmdboard_download = self.add_parser(
            cmdboard_subcommands, "download", caption="Скачать с доски"
        )
        self.add_argument(
            cmdboard_download,
            "folder",
            help="path to the folder to synchronize with a board.",
            caption="Папка",
        )
        self.add_argument(
            cmdboard_download,
            "--lists",
            help="Download only specified lists.",
            caption="Скачать только указанные списки (через запятую)",
        )
        self.add_argument(
            cmdboard_download,
            "--si",
            action="store_true",
            help="This flag includes card captions "
            "in .4s files. "
            "Useful for editing SI "
            "files (rather than CHGK)",
            caption="Формат Своей игры",
        )
        self.add_argument(
            cmdboard_download,
            "--replace_double_line_breaks",
            "-rd",
            action="store_true",
            help="This flag replaces double line breaks with single ones.",
            caption="Убрать двойные переносы строк",
        )
        self.add_argument(
            cmdboard_download,
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
            cmdboard_download,
            "--onlyanswers",
            action="store_true",
            help="This flag forces SI download to only include answers.",
            caption="Только ответы",
        )
        self.add_argument(
            cmdboard_download,
            "--noanswers",
            action="store_true",
            help="This flag forces SI download to not include answers.",
            caption="Без ответов",
        )
        self.add_argument(
            cmdboard_download,
            "--singlefile",
            action="store_true",
            help="This flag forces SI download all themes to single file.",
            caption="Склеить всё в один файл",
        )
        self.add_argument(
            cmdboard_download,
            "--qb",
            action="store_true",
            help="Quizbowl format",
            caption="Формат квизбола",
        )
        self.add_argument(
            cmdboard_download,
            "--labels",
            action="store_true",
            help="Use this if you also want to have lists based on labels.",
            caption="Создать файлы из лейблов Трелло",
        )

        cmdboard_upload = self.add_parser(
            cmdboard_subcommands, "upload", caption="Загрузить на доску"
        )
        self.add_argument(
            cmdboard_upload,
            "board_url",
            help="board url (trello.com/b/… or xy …/board/…).",
            caption="Ссылка на доску",
        )
        self.add_argument(
            cmdboard_upload,
            "filename",
            nargs="*",
            help="file(s) to upload to trello.",
            caption="Имя 4s-файла",
        )
        self.add_argument(
            cmdboard_upload,
            "--author",
            action="store_true",
            help="Display authors in cards' captions",
            caption="Дописать авторов в заголовок карточки",
        )
        self.add_argument(
            cmdboard_upload,
            "--list_name",
            help="List name where to upload cards",
            caption="Имя списка для загрузки карточек",
        )

        cmdboard_token = cmdboard_subcommands.add_parser("token")
        self.add_argument(
            cmdboard_token,
            "board_service_url",
            nargs="?",
            default="https://trello.com",
            help="board service url; determines the auth flow "
            "(trello OAuth vs xy token page). Default: https://trello.com",
            caption="Адрес сервиса доски",
        )
        self.add_argument(
            cmdboard_token,
            "--no-browser",
            action="store_true",
            help="Don't try to open in browser",
            caption="Не открывать браузер",
        )

        cmdhandouts = subparsers.add_parser("handouts")
        cmdhandouts_subcommands = cmdhandouts.add_subparsers(dest="handoutssubcommand")
        cmdhandouts_generate = self.add_parser(
            cmdhandouts_subcommands, "4s2hndt", aliases=["generate"]
        )
        self.add_argument(
            cmdhandouts_generate,
            "filename",
            help="file with questions packet",
            caption="Имя файла с пакетом",
            filetypes=[("chgksuite files", ("*.4s", "*.si4s", "*.br4s", "*.tr4s"))],
        )
        self.add_argument(
            cmdhandouts_generate,
            "--language",
            "-lang",
            default="ru",
            help="language",
            caption="Язык",
            argtype="radiobutton",
            choices=sorted(HANDOUT_LANGS),
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

        cmdhandouts_run = self.add_parser(
            cmdhandouts_subcommands, "hndt2pdf", aliases=["run"]
        )
        self.add_argument(
            cmdhandouts_run,
            "filename",
            help="file with handouts",
            caption="Имя файла с раздатками",
            filetypes=[("handouts files", "*.hndt"), ("text files", "*.txt")],
        )
        self.add_argument(
            cmdhandouts_run,
            "--language",
            "-lang",
            default="ru",
            argtype="radiobutton",
            choices=sorted(HANDOUT_LANGS),
            help="language",
            caption="Язык",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--compress_pdf",
            choices=["on", "off"],
            default="on",
            help="compress output PDF",
            caption="Сжать PDF после вёрстки",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdhandouts_run,
            "--optimize_images",
            choices=["on", "off"],
            default="on",
            help="recompress raster images before TeX rendering",
            caption="Сжать растровые картинки перед вёрсткой",
            advanced=True,
            argtype="radiobutton",
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
            default=None,
            help="tikz_mm width",
            caption="Ширина tikz_mm",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_run,
            "--add_n_teams",
            choices=["on", "off"],
            default="off",
            help="add _{n}teams suffix to output filename",
            caption="Добавить суффикс с количеством команд",
            advanced=True,
            argtype="radiobutton",
        )

        cmdhandouts_install = self.add_parser(cmdhandouts_subcommands, "install")
        self.add_argument(
            cmdhandouts_install,
            "--typst_package_regex",
            advanced=True,
            caption="Переопределить имя файла с релизом typst",
        )

        cmdhandouts_split_fit = self.add_parser(cmdhandouts_subcommands, "split_fit")
        self.add_argument(
            cmdhandouts_split_fit,
            "filename",
            help="source .hndt file",
            caption="Файл с раздатками",
            filetypes=[("handouts files", "*.hndt"), ("text files", "*.txt")],
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--output_dir",
            "-o",
            type=Path,
            help="where to write split handouts; defaults to the source directory",
            caption="Папка для выходных файлов",
            argtype="folder",
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--language",
            "-lang",
            default="ru",
            argtype="radiobutton",
            choices=sorted(HANDOUT_LANGS),
            help="language",
            caption="Язык",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--compress_pdf",
            choices=["on", "off"],
            default="on",
            help="compress final output PDFs",
            caption="Сжать итоговые PDF",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--optimize_images",
            choices=["on", "off"],
            default="on",
            help="recompress raster images before TeX rendering",
            caption="Сжать растровые картинки перед вёрсткой",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--max_rows",
            type=int,
            default=256,
            help="safety cap for row search",
            caption="Максимум строк для поиска",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--keep_pdfs",
            choices=["on", "off"],
            default="on",
            help="leave final fitted PDFs next to generated .hndt files",
            caption="Оставить PDF отдельных раздаток",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--no_auto_resize_images",
            action="store_true",
            help="disable the post-pass that shrinks image handouts to fit more rows",
            caption="Не подгонять размер картинок",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--image_bottom_space_row_ratio",
            type=float,
            default=0.6,
            help="shrink images only when bottom blank space exceeds this many row heights",
            caption="Порог пустого места в высотах строки",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--image_shrink_percent",
            type=float,
            default=2.0,
            help="shrink image handouts by this percent per probe",
            caption="Шаг уменьшения картинки, %",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--min_resize_image",
            type=float,
            default=0.6,
            help="do not shrink resize_image below this value",
            caption="Минимальный resize_image",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--no_update_source_resize",
            action="store_true",
            help="do not write final resize_image values back to the source .hndt",
            caption="Не обновлять resize_image в исходнике",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--no_all_q_pdf",
            action="store_true",
            help="do not create {source}_all_q_1team.pdf from the combined handouts",
            caption="Не создавать общий PDF",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--jobs",
            "-j",
            type=int,
            default=os.cpu_count() or 1,
            help="number of handouts to fit in parallel",
            caption="Параллельных задач",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--verbose",
            action="store_true",
            help="print every probed row count and resulting page count",
            caption="Подробный вывод",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--font",
            "-f",
            help="font",
            caption="Шрифт",
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--font_size",
            type=int,
            default=14,
            help="font size",
            caption="Размер шрифта",
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--paperwidth",
            type=float,
            default=210,
            help="paper width",
            caption="Ширина бумаги",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--paperheight",
            type=float,
            default=297,
            help="paper height",
            caption="Высота бумаги",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--margin_top",
            type=float,
            default=5,
            help="top margin",
            caption="Верхний отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--margin_bottom",
            type=float,
            default=5,
            help="bottom margin",
            caption="Нижний отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--margin_left",
            type=float,
            default=5,
            help="left margin",
            caption="Левый отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--margin_right",
            type=float,
            default=5,
            help="right margin",
            caption="Правый отступ",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--boxwidth",
            type=float,
            help="box width",
            caption="Ширина блока",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--boxwidthinner",
            type=float,
            help="box width inner",
            caption="Внутренняя ширина блока",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--tikz_mm",
            type=float,
            default=None,
            help="tikz_mm width",
            caption="Ширина tikz_mm",
            advanced=True,
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--add_n_teams",
            choices=["on", "off"],
            default="off",
            help="add _{n}teams suffix to output filename",
            caption="Добавить суффикс с количеством команд",
            advanced=True,
            argtype="radiobutton",
        )
        self.add_argument(
            cmdhandouts_split_fit,
            "--typst_package_regex",
            advanced=True,
            caption="Переопределить имя файла с релизом typst",
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
        self.add_argument(
            cmdhandouts_pack,
            "--compress_pdf",
            choices=["on", "off"],
            default="on",
            help="compress output PDF",
            caption="Сжать PDF после сборки",
            advanced=True,
            argtype="radiobutton",
        )

        cmdhandouts_create_html = self.add_parser(
            cmdhandouts_subcommands, "create_html"
        )
        self.add_argument(
            cmdhandouts_create_html,
            "fraction",
            help="fraction of A4 width: 1/6, 1/3, 1/2, or 1",
            caption="Доля ширины A4",
            choices=["1/6", "1/3", "1/2", "1"],
            argtype="radiobutton",
        )
        self.add_argument(
            cmdhandouts_create_html,
            "--font",
            "-f",
            help="font family",
            caption="Шрифт",
        )
        self.add_argument(
            cmdhandouts_create_html,
            "--output",
            "-o",
            help="output HTML filename",
            caption="Имя выходного HTML файла",
        )

        cmdhandouts_html2img = self.add_parser(cmdhandouts_subcommands, "html2img")
        self.add_argument(
            cmdhandouts_html2img,
            "filename",
            help="HTML file to convert",
            caption="HTML файл для конвертации",
            filetypes=[("HTML files", "*.html")],
        )
        self.add_argument(
            cmdhandouts_html2img,
            "--scale",
            "-s",
            type=int,
            default=4,
            help="PNG scale factor for high-DPI (default: 4)",
            caption="Масштаб PNG для высокого разрешения",
        )


def single_action(args, use_wrapper, resourcedir):
    if use_wrapper:
        args.console_mode = False
    else:
        args.console_mode = True

    if args.language in LANGS:
        args.regexes_file = os.path.join(resourcedir, f"regexes_{args.language}.json")
        if args.action == "parse":
            args.regexes = args.regexes_file
        args.labels_file = os.path.join(resourcedir, f"labels_{args.language}.toml")
    if not args.docx_template:
        args.docx_template = os.path.join(resourcedir, "template.docx")
    if not args.pptx_config:
        args.pptx_config = os.path.join(resourcedir, "pptx_config.toml")
    if not getattr(args, "pdf_config", None):
        args.pdf_config = os.path.join(resourcedir, "pdf_config.toml")
    if not getattr(args, "poll_config", None):
        args.poll_config = os.path.join(resourcedir, "poll_config.toml")
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
    # For compose, detect game from file extension (no --game flag needed)
    if args.action == "compose":
        filename = getattr(args, "filename", None)
        if isinstance(filename, list) and filename:
            filename = filename[0]
        if filename:
            args.game = ext_to_game(filename) or "chgk"
        else:
            args.game = "chgk"
    if args.action == "parse":
        gui_parse(args)
    if args.action == "compose":
        gui_compose(args)
    if args.action in ("board", "trello"):
        gui_board(args)
    if args.action == "handouts":
        gui_handouter(args)


def app():
    _, resourcedir = get_source_dirs()
    parser = argparse.ArgumentParser(prog="chgksuite")
    ArgparseBuilder(parser, False).build()
    args = DefaultNamespace(parser.parse_args())
    single_action(args, False, resourcedir)
