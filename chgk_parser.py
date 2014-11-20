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
import typotools
import traceback
import datetime

debug = False

QUESTION_LABELS = ['handout', 'question', 'answer',
        'zachet', 'nezachet', 'comment', 'source', 'author']

def make_filename(s):
    return os.path.splitext(s)[0]+'-out'+os.path.splitext(s)[1]

def debug_print(s):
    if debug == True:
        sys.stderr.write(s+'\n')

def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0]+indices, indices+[None])]

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
    5. Prettify input
    6. Pack Questions into dicts
    7. Return the resulting structure

    """

    BADNEXTFIELDS = set(['question', 'answer'])

    WHITESPACE = set([' ', ' ', '\n'])
    PUNCTUATION = set([',', '.', ':', ';', '?', '!'])

    re_tour = re.compile(r'Тур [0-9]*[\.:]', re.I)
    re_question = re.compile(r'Вопрос [0-9]*[\.:]', re.I)
    re_answer = re.compile(r'Ответ[\.:]', re.I)
    re_zachet = re.compile(r'Зач[её]т[\.:]', re.I)
    re_nezachet = re.compile(r'Незач[её]т[\.:]', re.I)
    re_comment = re.compile(r'Комментарий[\.:]', re.I)
    re_author = re.compile(r'Автор\(?ы?\)?[\.:]', re.I)
    re_source = re.compile(r'Источник\(?и?\)?[\.:]', re.I)
    re_editor = re.compile(r'Редактор(ы|ская группа)?[\.:]', re.I)
    re_date = re.compile(r'Дата[\.:]', re.I)
    re_handout = re.compile(r'Разда(ча|тка|точный материал)[\.:]', re.I)

    regexes = {
        'tour' : re_tour,
        'question' : re_question,
        'answer' : re_answer,
        'zachet' : re_zachet,
        'nezachet' : re_nezachet,
        'comment' : re_comment,
        'author' : re_author,
        'source' : re_source,
        'editor' : re_editor,
        'date' : re_date,
    }

    chgk_parse.structure = []

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

    i = 0
    st = chgk_parse.structure
    while i < len(st):
        matching_regexes = {(regex, regexes[regex].search(st[i][1]).start(0)) 
        for regex in regexes if regexes[regex].search(st[i][1])}
        
        # If more than one regex matches string, split it and 
        # insert into structure separately.
        
        if len(matching_regexes) == 1: 
            st[i][0] = matching_regexes.pop()[0]
        elif len(matching_regexes) > 1:
            sorted_r = sorted(matching_regexes, key=lambda x: x[1])
            slices = []
            for j in range(1, len(sorted_r)):
                slices.append(
                    [sorted_r[j][0], st[i][1][
                        sorted_r[j][1] 
                         : 
                        sorted_r[j+1][1] if j+1 < len(sorted_r)
                                                else len(st[i][1])]])
            for slice_ in slices:
                chgk_parse.structure.insert(
                    i+1, slice_)
            st[i][0] = sorted_r[0][0]
            st[i][1] = st[i][1][:sorted_r[1][1]]
        i += 1
    chgk_parse.structure = st
    i = 0
        

    # 2.

    merge_y_to_x('question','answer')
    merge_to_x_until_nextfield('source')
    merge_to_x_until_nextfield('sources')
    merge_to_x_until_nextfield('answer')
    merge_to_x_until_nextfield('comment')

    # 3.

    i = 0
    while i < len(chgk_parse.structure):
        if (chgk_parse.structure[i][0] == 'answer' 
            and chgk_parse.structure[i-1][0] not in ('question',
                'newquestion')):
            chgk_parse.structure.insert(i,['newquestion',''])
            i = 0
        i += 1
    
    i = 0
    while i < len(chgk_parse.structure) - 1:
        if (chgk_parse.structure[i][0] == ''
            and chgk_parse.structure[i+1][0] == 'newquestion'):
            merge_to_next(i)
            i = 0
        i += 1

    for element in chgk_parse.structure:
        if element[0] == 'newquestion':
            element[0] = 'question'

    # 4.

    for element in chgk_parse.structure:
        if element[0] == '':
            element[0] = 'meta'
        if element[0] in regexes:
            element[1] = regexes[element[0]].sub('', element[1])

    # 5.

    for element in chgk_parse.structure:
        
        # find handouts

        if element[0] == 'question':
            
            handouts = []
            while re_handout.search(element[1]):
                handout = re_handout.search(element[1])
                if (handout.start() > 0 and element[1][handout.start() - 1]
                    in typotools.OPENING_BRACKETS and not
                    typotools.find_matching_closing_bracket(element[1],
                        handout.start()-1) is None):
                    part = partition(element[1], [handout.start()-1, 
                        typotools.find_matching_closing_bracket(element[1],
                        handout.start()-1)+1])
                else:
                    part = partition(element[1], [handout.start(), 
                        handout.start() 
                        + element[1][handout.start():].index('\n')])
                assert len(part) == 3
                element[1] = part[0] + part[2]
                handouts.append(part[1])
            if len(handouts) > 0:
                chgk_parse.structure.insert(
                    chgk_parse.structure.index(element)+1, ['handout', 
                    handouts[0] if len(handouts) == 1 else handouts])

        # typogrify

        if element[0] != 'date':
            element[1] = typotools.typography(element[1])
        
        # detect inner lists

        mo = {m for m 
            in re.finditer(r'(\s+|^)(\d+)[\.\)]\s*(?!\d)',element[1], re.U)}
        if len(mo) > 1:
            sorted_up = sorted(mo, key=lambda m: int(m.group(2)))
            j = 0
            list_candidate = []
            while j == int(sorted_up[j].group(2)) - 1:
                list_candidate.append((j+1, sorted_up[j].group(0), 
                    sorted_up[j].start()))
                if j+1 < len(sorted_up):
                    j += 1
                else:
                    break
            if len(list_candidate) > 1:
                if (element[0] != 'question' or 
                    (element[0] == 'question'
                        and 'дуплет' in element[1].lower() 
                            or 'блиц' in element[1].lower())):
                    part = partition(element[1], [x[2] for x in
                        list_candidate])
                    lc = 0
                    while lc < len(list_candidate):
                        part[lc+1] = part[lc+1].replace(list_candidate[lc][1], '')
                        lc += 1
                    element[1] = ([part[0], part[1:]] if part[0] != ''
                                            else part[1:])

        # turn source into list if necessary

        if (element[0] == 'source' and isinstance(element[1], basestring)
                    and len(element[1].split('\n')) > 1):
            element[1] = element[1].split('\n')




    # 6.

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


    # 7.

    return final_structure

def compose_4s(structure):
    types_mapping = {
        'meta' : '# ',
        'editor': '#EDITOR ',
        'date': '#DATE ',
        'question': '? ',
        'answer': '! ',
        'zachet': '= ',
        'nezachet': '!= ',
        'source': '^ ',
        'comment': '/ ',
        'author': '@ ',
        'handout': '> ',
        'Question': None,
    }
    def format_element(z):
        if isinstance(z, basestring):
            return z
        elif isinstance(z, list):
            if isinstance(z[1], list):
                return z[0] + '\n- ' + '\n- '.join(z[1])
            else:
                return '\n- ' + '\n- '.join(z)
    result = ''
    for element in structure:
        if types_mapping[element[0]]:
            result += (types_mapping[element[0]] 
                + format_element(element[1]) + '\n\n')
        elif element[0] == 'Question':
            for label in QUESTION_LABELS:
                if label in element[1]:
                    result += (types_mapping[label]
                        + format_element(element[1][label]) + '\n')
            result += '\n'
    return result



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
        output_file.write(
            compose_4s(final_structure))

if __name__ == "__main__":
    main()