#!usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
import re
import traceback

OPENING_QUOTES = set(['«', '„', '“', '‘'])
CLOSING_QUOTES = set(['»', '“', '”', '’'])
QUOTES = OPENING_QUOTES | CLOSING_QUOTES | set(['"', "'"])
WHITESPACE = set([' ', ' ', '\n'])
PUNCTUATION = set([',', '.', ':', ';', '?', '!'])
OPENING_BRACKETS = ['[', '(', '{']
CLOSING_BRACKETS = [']', ')', '}']
BRACKETS = set(OPENING_BRACKETS) | set(CLOSING_BRACKETS)

re_bad_wsp_start = re.compile(r'^[{}]+'.format(''.join(WHITESPACE)))
re_bad_wsp_end = re.compile(r'[{}]+$'.format(''.join(WHITESPACE)))

def remove_excessive_whitespace(s):
    s = re_bad_wsp_start.sub('', s)
    s = re_bad_wsp_end.sub('', s)
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
    text = re.sub(r"""^'(?=%s\\B)""" % (punct_class,), '«', text)
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

    # Any remaining single quotes should be opening ones:
    text = re.sub("'", '«', text)

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
    s = re.sub(r'(?<=\d)-','–',s)
    s = re.sub(r'-(?=\d)','−',s)
    return s

def typography(s):
    s = remove_excessive_whitespace(s)
    s = get_quotes_right(s)
    s = get_dashes_right(s)
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
    return None

