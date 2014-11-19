#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import pprint
import urllib
import re
import os
import sys
import codecs
import json
import yaml

debug = False

def make_filename(s):
    return os.path.splitext(s)[0]+'-out'+os.path.splitext(s)[1]

def debug_print(s):
    if debug == True:
        sys.stderr.write(s+'\n')


def chgk_parse(text):

    """
    Parsing rationale: every Question has two required fields: 'question' and
    the immediately following 'answer'. All the rest are optional, as is
    the order of these fields. On the other hand, everything
    except the 'question' is obligatorily marked, while the 'question' is
    optionally marked. But IF the question is not marked, 'meta' comments
    between Questions will not be parsed as 'meta' but will be merged to
    'question's.
    Parsing is done by regexes in the following steps:

    1. Identify all the fields you can, mark them with their respective
        labels, mark all the others with ''
    2. Merge fields inside Question with '' lines between them
    3. Ensure every 'answer' has a 'question'
    4. Mark all remaining '' fields as 'meta'
    5. Pack Questions into dicts
    6. Return the resulting structure

    """

    re_tour = re.compile(r'^Тур [0-9]*[\.:]', re.I)
    re_question = re.compile(r'^Вопрос [0-9]*[\.:]', re.I)
    re_answer = re.compile(r'^Ответ[\.:]', re.I)
    re_zachet = re.compile(r'^Зач[её]т[\.:]', re.I)
    re_nezachet = re.compile(r'Незач[её]т[\.:]', re.I)
    re_comment = re.compile(r'^Комментарий[\.:]', re.I)
    re_author = re.compile(r'^Автор(\(ы\))?[\.:]', re.I)
    re_authors = re.compile(r'^Авторы[\.:]', re.I)
    re_source = re.compile(r'^Источник(\(и\))?[\.:]', re.I)
    re_sources = re.compile(r'^Источники[\.:]', re.I)

    regexes = {
        'tour' : re_tour,
        'question' : re_question,
        'answer' : re_answer,
        'zachet' : re_zachet,
        'nezachet' : re_nezachet,
        'comment' : re_comment,
        'author' : re_author,
        'authors' : re_authors,
        'source' : re_source,
        'sources' : re_sources,
    }

    chgk_parse.structure = []

    BADNEXTFIELDS = set(['question', 'answer'])
    QUESTION_LABELS = set(['question', 'answer',
        'zachet', 'nezachet', 'comment', 'author',
        'authors', 'source', 'sources'])

    def merge_to_previous(index):
        target = index - 1
        chgk_parse.structure[target][1] = (
            chgk_parse.structure[target][1] + '\n' 
            + chgk_parse.structure.pop(index)[1])

    def merge_to_next(index):
        target = chgk_parse.structure.pop(index)
        chgk_parse.structure[index][1] = (target[1] + '\n' 
            + chgk_parse.structure[index][1])

    def find_next_specific_field(index, fieldname):
        target = index + 1
        while chgk_parse.structure[target][0] != fieldname:
            target += 1
        return target

    def find_next_fieldname(index):
        target = index + 1
        while chgk_parse.structure[target][0] == '':
            target += 1
        return chgk_parse.structure[target][0]

    def merge_y_to_x(x, y):
        i = 0
        while i < len(chgk_parse.structure):
            if chgk_parse.structure[i][0] == x:
                while (i+1 < len(chgk_parse.structure) 
                    and chgk_parse.structure[i+1][0] != y):
                    merge_to_previous(i+1)
            i += 1

    def merge_to_x_until_nextfield(x):
        i = 0
        while i < len(chgk_parse.structure):
            if chgk_parse.structure[i][0] == x:
                while (i+1 < len(chgk_parse.structure) 
                    and chgk_parse.structure[i+1][0] == ''
                    and find_next_fieldname(i) not in BADNEXTFIELDS):
                    merge_to_previous(i+1)
            i += 1

    def swap_elements(x, y):
        z = chgk_parse.structure[y]
        chgk_parse.structure[y] = chgk_parse.structure[x]
        chgk_parse.structure[x] = z

    # 1.

    for x in text.split('\n'):
        if x != '':
            chgk_parse.structure.append(['',x])

    for element in chgk_parse.structure:
        for regexp in regexes:
            if regexes[regexp].search(element[1]):
                element[0] = regexp

    # 2.

    merge_y_to_x('question','answer')
    merge_to_x_until_nextfield('source')
    merge_to_x_until_nextfield('answer')
    merge_to_x_until_nextfield('comment')

    # 3.

    i = 0
    while i < len(chgk_parse.structure):
        if (chgk_parse.structure[i][0] == 'answer' 
            and chgk_parse.structure[i-1][0] != 'question'):
            chgk_parse.structure.insert(i,['question',''])
            i = 0
        i += 1
    
    i = 0
    while i < len(chgk_parse.structure) - 1:
        if (chgk_parse.structure[i][0] == ''
            and chgk_parse.structure[i+1][0] == 'question'):
            merge_to_next(i)
            i = 0
        i += 1

    merge_y_to_x('author','question')
    merge_y_to_x('authors','question')
    merge_y_to_x('comment','question')
    merge_y_to_x('source','question')
    merge_y_to_x('sources','question')

    # 4.

    for element in chgk_parse.structure:
        if element[0] == '':
            element[0] = 'meta'
        if element[0] in regexes:
            element[1] = regexes[element[0]].sub('', element[1])

    # 5.

    final_structure = []
    current_question = {}

    for element in chgk_parse.structure:
        if element[0] in set(['question', 'meta']): 
            if current_question != {}:
                final_structure.append(['Question', current_question])
                current_question = {}
        if element[0] in QUESTION_LABELS:
            if element[0] in current_question:
                current_question[element[0]] += '\n' + element[1]
            else:
                current_question[element[0]] = element[1]
        else:
            final_structure.append([element[0], element[1]])
    if current_question != {}:
        final_structure.append(['Question', current_question])

    # 6.

    return final_structure

def main():

    global debug

    sys.stderr = codecs.getwriter('utf8')(sys.stderr)

    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--debug', '-d', action='store_true')
    args = parser.parse_args()

    if args.debug:
        debug = True

    with codecs.open(args.filename, 'r', 'utf8') as input_file:
            input_text = input_file.read()

    input_text = input_text.replace('\r','')

    final_structure = chgk_parse(input_text)

    with codecs.open(
        make_filename(args.filename), 'w', 'utf8') as output_file:
        output_file.write(pprint.pformat(final_structure).decode('unicode_escape'))

if __name__ == "__main__":
    main()