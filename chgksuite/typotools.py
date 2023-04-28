#!usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import re
import functools
import unicodedata
try:
    import urllib
    unquote = urllib.unquote
except AttributeError:
    import urllib.parse
    unquote = urllib.parse.unquote_to_bytes
try:
    basestring
except NameError:
    basestring = str

OPENING_QUOTES = set(['«', '„', '“'])
CLOSING_QUOTES = set(['»', '“', '”'])
QUOTES = OPENING_QUOTES | CLOSING_QUOTES | set(['"', "'"])
WHITESPACE = set([' ', ' ', '\n'])
PUNCTUATION = set([',', '.', ':', ';', '?', '!'])
OPENING_BRACKETS = ['[', '(', '{']
CLOSING_BRACKETS = [']', ')', '}']
BRACKETS = set(OPENING_BRACKETS) | set(CLOSING_BRACKETS)
LOWERCASE_RUSSIAN = set(list('абвгдеёжзийклмнопрстуфхцчшщъыьэюя'))
UPPERCASE_RUSSIAN = set(list('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'))
POTENTIAL_ACCENTS = set(list('АОУЫЭЯЕЮИ'))
BAD_BEGINNINGS = set(['Мак', 'мак', "О'", 'о’', 'О’', "о'"])
NO_BREAK_SEQUENCES = [
    "а",
    "без",
    "в",
    "во",
    "где",
    "для",
    "же",
    "за",
    "и",
    "или",
    "из",
    "из-за",
    "к",
    "как",
    "на",
    "над",
    "не",
    "ни",
    "но",
    "о",
    "от",
    "по",
    "под",
    "при",
    "с",
    "со",
    "то",
    "у",
    "что",
    "перед"
]
NO_BREAK_SEQUENCES_LEFT = [
    "бы",
    "ли",
    "же"
]
LETTERS_MAPPING = {"a": "а", "e": "е", "y": "у", "o": "о", "u": "и"}
for x in list(LETTERS_MAPPING.keys()):
    LETTERS_MAPPING[x.upper()] = LETTERS_MAPPING[x].upper()
CYRILLIC_CHARS = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
СYRILLIC_CHARS = set(CYRILLIC_CHARS + CYRILLIC_CHARS.upper())

re_bad_wsp_start = re.compile(r'^[{}]+'.format(''.join(WHITESPACE)))
re_bad_wsp_end = re.compile(r'[{}]+$'.format(''.join(WHITESPACE)))
re_url = re.compile(r"""((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]"""
                    """|[a-z0-9.\\-]+[.‌​][a-z]{2,4}/)(?:[^\\s()<>]+|(([^\\s()<>]+|(([^\\s()<>]+)))*))+"""
                    """(?:(([^\\s()<>]+|(‌​([^\\s()<>]+)))*)|[^\\s`!()[]{};:'".,<>?«»“”‘’]))""",
                    re.DOTALL)
re_percent = re.compile(r"(%[0-9a-fA-F]{2})+")


def strings_iterator(str_):
    result = []
    if isinstance(str_, str):
        return [str_]
    elif isinstance(str_, list):
        for el in str_:
            result.extend(strings_iterator(el))
    elif isinstance(str_, dict):
        for v in str_.values():
            result.extend(strings_iterator(v))
    return result


@functools.cache
def uni_normalize(k):
    return unicodedata.normalize("NFD", k)


def cyr_lat_check_char(i, char, word):
    if char in CYRILLIC_CHARS:
        return
    if not (
        (i == 0 or word[i - 1] in CYRILLIC_CHARS or not word[i - 1].isalpha())
        and (
            i == len(word) - 1
            or word[i + 1] in CYRILLIC_CHARS
            or not word[i + 1].isalpha()
        )
    ):
        return
    norm = uni_normalize(char)
    if norm != char and norm[0] in LETTERS_MAPPING:
        if len(norm) > 1 and norm[1] == "\u0300":
            return LETTERS_MAPPING[norm[0]] + "\u0301" + norm[2:]
        return LETTERS_MAPPING[norm[0]] + norm[1:]
    return


ACCENTS_TO_FIX = {"\u0301", "\u0341"}


def cyr_lat_check_word(word):
    if len(word) == 1:
        return
    replacements = {}
    for i, char in enumerate(word):
        check_result = cyr_lat_check_char(i, char, word)
        if check_result:
            replacements[char] = check_result
        elif (
            char in CYRILLIC_CHARS
            and i < len(word) - 1
            and word[i + 1] in ACCENTS_TO_FIX
        ):
            replacements[char + word[i + 1]] = char + "\u0300"
    if replacements:
        for k in replacements:
            word = word.replace(k, replacements[k])
        return word
    return


def fix_accents_func(str_):
    str_ = detect_accent(str_)
    replacements = {}
    for word in str_.strip():
        if check := cyr_lat_check_word(word):
            replacements[word] = check
    for rep in replacements:
        str_ = str_.replace(rep, replacements[rep])
    return str_


def remove_excessive_whitespace(s):
    s = re_bad_wsp_start.sub('', s)
    s = re_bad_wsp_end.sub('', s)
    s = re.sub(r'\s+\n\s+', '\n', s)
    return s


def get_quotes_right(s_in):
    s = s_in
    s = re.sub(r'[{}]'.format(''.join(OPENING_QUOTES)), '«', s)
    s = re.sub(r'[{}]'.format(''.join(CLOSING_QUOTES)), '»', s)
    s = re.sub(r'^"', '«', s)
    s = re.sub(r'"$', '»', s)
    s = re.sub(r'(\w)(")([^\w]|$)', r'\1»\3', s, flags=re.U)
    s = re.sub(r'(^|[^\w])(")(\w)', r'\1«\3', s, flags=re.U)
    s = re.sub(r'([^\w\s])(")([^\w\s])', r'\1»\3', s, flags=re.U)
    s = re.sub(r'" ', '» ', s)
    s = re.sub(r' "', ' «', s)
    cntr = 0

    s = list(s)
    for i, c in enumerate(s):
        if c == '"':
            if cntr:
                s[i] = '»'
                cntr -= 1
            else:
                s[i] = '«'
                cntr += 1

    cntr = 0
    for i, c in enumerate(s):
        if c == '«':
            cntr += 1
            if cntr % 2 == 0:
                s[i] = '„'
        if c == '»':
            if cntr % 2 == 0:
                s[i] = '“'
            cntr -= 1
    s = ''.join(s)

    s = re.sub(r"(\w)'", r'\1’', s, flags=re.U)
    s = re.sub(r"'(\w)", r'‘\1', s, flags=re.U)

    return s


def get_dashes_right(s):
    s = re.sub(r'(?<=\s)-+(?=\s)', '—', s)
    s = s.replace(" – ", " — ")
    return s


def replace_no_break_spaces(s):
    for sp in (NO_BREAK_SEQUENCES + [x.title() for x in NO_BREAK_SEQUENCES]):
        r_from = "(^|[ \u00a0]){sp} ".format(sp=sp)
        r_to = "\\g<1>{sp}\u00a0".format(sp=sp)
        s = re.sub(r_from, r_to, s)
    for sp in (NO_BREAK_SEQUENCES_LEFT + [x.title() for x in NO_BREAK_SEQUENCES_LEFT]):
        r_from = " {sp}([ \u00a0]|$)".format(sp=sp)
        r_to = "\u00a0{sp}\\g<1>".format(sp=sp)
        s = re.sub(r_from, r_to, s)
    return s


def search_accent(s):
    return re.search("([а-яё])([АОУЫЭЯЕЮИ])([^А-ЯЁ])", s) or re.search(
        "[^А-ЯЁ]([А-ЯЁ])([АОУЫЭЯЕЮИ])([^А-ЯЁ])", s
    )


def detect_accent(s):
    for word in re.split(r'[^{}{}]+'.format(
            ''.join(LOWERCASE_RUSSIAN), ''.join(UPPERCASE_RUSSIAN)), s):
        if word.upper() != word and len(word) > 1:
            try:
                i = 1
                word_new = word
                while i < len(word_new):
                    if (word_new[i] in POTENTIAL_ACCENTS and
                            word_new[:i] not in BAD_BEGINNINGS):
                        word_new = word_new[:i] + \
                            word_new[i].lower() + '\u0301' + word_new[i + 1:]
                    i += 1
                if word != word_new:
                    s = (s[:s.index(word)] + word_new +
                         s[s.index(word) + len(word):])
            except:
                print(repr(word))
    return s


def percent_decode(s):
    grs = sorted([match.group(0)
                  for match in re_percent.finditer(s)], key=len, reverse=True)
    for gr in grs:
        try:
            s = s.replace(gr, unquote(gr.encode('utf8')).decode('utf8'))
        except:
            pass
    return s


def recursive_typography(s, **kwargs):
    if isinstance(s, basestring):
        s = typography(s, **kwargs)
        return s
    elif isinstance(s, list):
        new_s = []
        for element in s:
            new_s.append(recursive_typography(element, **kwargs))
        return new_s


def typography(s, wsp=True, quotes=True,
               dashes=True, accents=True, percent=True, fix_accents=True):
    if wsp:
        s = remove_excessive_whitespace(s)
    if quotes:
        s = get_quotes_right(s)
    if dashes:
        s = get_dashes_right(s)
    if accents:
        s = fix_accents_func(s)
    if percent:
        s = percent_decode(s)
    return s


def matching_bracket(s):
    assert s in OPENING_BRACKETS or s in CLOSING_BRACKETS
    if s in OPENING_BRACKETS:
        return CLOSING_BRACKETS[OPENING_BRACKETS.index(s)]
    return OPENING_BRACKETS[CLOSING_BRACKETS.index(s)]


def find_matching_closing_bracket(s, index):
    s = list(s)
    i = index
    assert s[i] in OPENING_BRACKETS
    ob = s[i]
    cb = matching_bracket(ob)
    counter = 0
    while i < len(s):
        if s[i] == ob:
            counter += 1
        if s[i] == cb:
            counter -= 1
            if counter == 0:
                return i
        i += 1
    return None


def find_matching_opening_bracket(s, index):
    s = list(s)
    i = index
    assert s[i] in CLOSING_BRACKETS
    cb = s[i]
    ob = matching_bracket(cb)
    counter = 0
    if i < 0:
        i = len(s) - abs(i)
    while i < len(s) and i >= 0:
        if s[i] == cb:
            counter += 1
        if s[i] == ob:
            counter -= 1
            if counter == 0:
                return i
        i -= 1
    return None
