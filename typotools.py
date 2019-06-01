#!usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import re
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

re_bad_wsp_start = re.compile(r'^[{}]+'.format(''.join(WHITESPACE)))
re_bad_wsp_end = re.compile(r'[{}]+$'.format(''.join(WHITESPACE)))
re_url = re.compile(r"""((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]"""
                    """|[a-z0-9.\-]+[.‌​][a-z]{2,4}/)(?:[^\s()<>]+|(([^\s()<>]+|(([^\s()<>]+)))*))+"""
                    """(?:(([^\s()<>]+|(‌​([^\s()<>]+)))*)|[^\s`!()[]{};:'".,<>?«»“”‘’]))""",
                    re.DOTALL)
re_percent = re.compile(r"(%[0-9a-fA-F]{2})+")


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
    # s = re.sub(r'(?<=\d)-(?<=\d)','–',s)
    # s = re.sub(r'-(?=\d)','−',s)
    return s


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


def recursive_typography(s):
    if isinstance(s, basestring):
        s = typography(s)
        return s
    elif isinstance(s, list):
        new_s = []
        for element in s:
            new_s.append(recursive_typography(element))
        return new_s


def typography(s, wsp=True, quotes=True,
               dashes=True, accents=True, percent=True):
    if wsp:
        s = remove_excessive_whitespace(s)
    if quotes:
        s = get_quotes_right(s)
    if dashes:
        s = get_dashes_right(s)
    if accents:
        s = detect_accent(s)
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
