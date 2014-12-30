#!usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
import re
import traceback
import urllib
import pprint

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
"""(?:(([^\s()<>]+|(‌​([^\s()<>]+)))*)|[^\s`!()[]{};:'".,<>?«»“”‘’]))""", re.DOTALL) 
re_percent = re.compile(ur"(%[0-9a-fA-F]{2})+")

def remove_excessive_whitespace(s):
    s = re_bad_wsp_start.sub('', s)
    s = re_bad_wsp_end.sub('', s)
    s = re.sub(r'\s+\n\s+', '\n', s)
    return s


def convert_quotes(text):
    """
    Convert quotes in *text* into HTML curly quote entities.

    >>> print(convert_quotes('"Isn\\'t this fun?"'))
    &#8220;Isn&#8217;t this fun?&#8221;
    """

    punct_class = r"""[!"#\$\%'()*+,-.\/:;<=>?\@\[\\\]\^_`{|}~]"""

    # Special case if the very first character is a quote
    # followed by punctuation at a non-word-break. Close the quotes by brute
    # force:
    text = re.sub(r"""^"(?=%s\\B)""" % (punct_class,), '«', text)

    # Special case for double sets of quotes, e.g.:
    #   <p>He said, "'Quoted' words in a larger quote."</p>
    text = re.sub(r""""'(?=\w)""", '««', text)
    text = re.sub(r"""'"(?=\w)""", '««', text)

    # Special case for decade abbreviations (the '80s):
    text = re.sub(r"""\b'(?=\d{2}s)""", '’', text)

    close_class = r'[^\ \t\r\n\[\{\(\-]'
    dec_dashes = '–|—'

    # Get most opening single quotes:
    opening_single_quotes_regex = re.compile(r"""
            (
                \s          |   # a whitespace char, or
                &nbsp;|     |   # a non-breaking space entity, or
                --          |   # dashes, or
                &[mn]dash;  |   # named dash entities
                %s          |   # or decimal entities
                &\#x201[34];    # or hex
            )
            '                 # the quote
            (?=\w)            # followed by a word character
            """ % (dec_dashes,), re.VERBOSE)
    text = opening_single_quotes_regex.sub(r'\1«', text)

    closing_single_quotes_regex = re.compile(r"""
            (%s)
            '
            (?!\s | s\b | \d)
            """ % (close_class,), re.VERBOSE)
    text = closing_single_quotes_regex.sub(r'\1»', text)

    closing_single_quotes_regex = re.compile(r"""
            (%s)
            '
            (\s | s\b)
            """ % (close_class,), re.VERBOSE)
    text = closing_single_quotes_regex.sub(r'\1»\2', text)

    # Get most opening double quotes:
    opening_double_quotes_regex = re.compile(r"""
            (
                \s          |   # a whitespace char, or
                &nbsp;      |   # a non-breaking space entity, or
                --          |   # dashes, or
                &[mn]dash;  |   # named dash entities
                %s          |   # or decimal entities
                &\#x201[34];    # or hex
            )
            "                 # the quote
            (?=\w)            # followed by a word character
            """ % (dec_dashes,), re.VERBOSE)
    text = opening_double_quotes_regex.sub(r'\1«', text)

    # Double closing quotes:
    closing_double_quotes_regex = re.compile(r"""
            #(%s)?   # character that indicates the quote should be closing
            "
            (?=\s)
            """ % (close_class,), re.VERBOSE)
    try:
        text = closing_double_quotes_regex.sub('»', text)
    except:
        print(repr(traceback.format_exc()))

    closing_double_quotes_regex = re.compile(r"""
            (%s)   # character that indicates the quote should be closing
            "
            """ % (close_class,), re.VERBOSE)
    text = closing_double_quotes_regex.sub(r'\1»', text)

    # Any remaining quotes should be opening ones.
    text = re.sub('"', '«', text)

    return text

def get_next_opening_quote_character(s, index):
    i = index + 1
    while i < len(s):
        if s[i] in OPENING_QUOTES:
            return s[i], i
        i += 1
    return '', ''

def get_next_quote_character(s, index):
    i = index + 1
    while i < len(s):
        if s[i] in QUOTES:
            return s[i], i
        i += 1
    return '', ''

def get_next_closing_quote_character(s, index):
    i = index + 1
    while i < len(s):
        if s[i] in CLOSING_QUOTES:
            return s[i], i
        i += 1
    return '', ''

def get_quotes_right(s):
    # s = re.sub(r'(?<=[{}{}{}])["\']'.format(''.join(WHITESPACE), 
    #     ''.join(CLOSING_QUOTES), ''.join(PUNCTUATION)), '«', s)
    # s = re.sub(r'["\'](?=[{}{}{}])'.format(''.join(WHITESPACE), 
    #     ''.join(OPENING_QUOTES), ''.join(PUNCTUATION)), '»', s)
    s = re.sub(r'“','"',s)
    s = re.sub(r'[{}]'.format(''.join(OPENING_QUOTES)), '«', s)
    s = re.sub(r'[{}]'.format(''.join(CLOSING_QUOTES)), '»', s)
    s = convert_quotes(s)
    
    # alternate quotes

    i = 0
    s = list(s)
    if get_next_quote_character(s, -1)[0]:
        s[get_next_quote_character(s, -1)[1]] = '«'
    while i < len(s):
        if (s[i] == '«' 
            and get_next_quote_character(s, i)[0] == '«'):
            s[get_next_quote_character(s, i)[1]] = '„'
        i += 1
    s = s[::-1]
    if get_next_quote_character(s, -1)[0]:
        s[get_next_quote_character(s, -1)[1]] = '»'
    i = 0
    while i < len(s):
        if (s[i] == '»' 
            and get_next_quote_character(s, i)[0] == '»'):
            s[get_next_quote_character(s, i)[1]] = '“'
        i += 1
    s = s[::-1]
    s = ''.join(s)
    return s

def get_dashes_right(s):
    s = re.sub(r'(?<=\s)-+(?=\s)','—',s)
    s = re.sub(r'(?<=\d)-(?<=\d)','–',s)
    s = re.sub(r'-(?=\d)','−',s)
    return s

def detect_accent(s):
    for word in re.split(r'[^{}{}]+'.format(
        ''.join(LOWERCASE_RUSSIAN),''.join(UPPERCASE_RUSSIAN)),s):
        if word.upper() != word and len(word) > 1:
            try:
                i = 1
                word_new = word
                while i < len(word_new):
                    if (word_new[i] in POTENTIAL_ACCENTS and word_new[:i] not in
                            BAD_BEGINNINGS):
                        word_new = word_new[:i] + '`' + word_new[i].lower() + word_new[i+1:]
                    i += 1
                if word != word_new:
                    s = (s[:s.index(word)] + word_new
                        + s[s.index(word)+len(word):])
            except:
                print(repr(word))
    return s

def percent_decode(s):
    grs = sorted([match.group(0) 
        for match in re_percent.finditer(s)], key=len, reverse=True)
    for gr in grs:
        try:
            s = s.replace(gr,urllib.unquote(gr.encode('utf8')).decode('utf8'))
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

def typography(s):
    s = remove_excessive_whitespace(s)
    s = get_quotes_right(s)
    s = get_dashes_right(s)
    s = detect_accent(s)
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

