#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import argparse
import pprint
import urllib
import re
import os
import pdb
import sys
import codecs
import json
import typotools
import traceback
import subprocess
import shlex
import datetime
from typotools import remove_excessive_whitespace, WHITESPACE, \
    PUNCTUATION, recursive_typography

QUESTION_LABELS = ['handout', 'question', 'answer',
        'accept', 'reject', 'comment', 'source', 'author', 'number',
        'setcounter']
SEP = os.linesep
ENC = sys.getdefaultencoding()
if ENC == 'ascii':
    ENC = 'cp866'
re_tour = re.compile(r'^ТУР ?([0-9IVXLCDM]*)([\.:])?$', re.I | re.U)
re_tourrev = re.compile(r'^([0-9]+) ТУР([\.:])?$', re.I | re.U)
re_question = re.compile(r'ВОПРОС ?[№N]?([0-9]*) ?[\.:]', re.I | re.U)
re_answer = re.compile(r'ОТВЕТЫ? ?[№N]?([0-9]+)? ?[:]', re.I | re.U)
re_accept = re.compile(r'ЗАЧ[ЕЁ]Т ?[\.:]', re.I | re.U)
re_reject = re.compile(r'НЕЗАЧ[ЕЁ]Т ?[\.:]', re.I | re.U)
re_comment = re.compile(r'КОММЕНТАРИЙ ?[№N]?([0-9]+)? ?[\.:]', re.I | re.U)
re_author = re.compile(r'АВТОР\(?Ы?\)? ?[\.:]', re.I | re.U)
re_source = re.compile(r'ИСТОЧНИК\(?И?\)? ?[\.:]', re.I | re.U)
re_editor = re.compile(r'РЕДАКТОР(Ы|СКАЯ ГРУППА)? ?[\.:]', re.I | re.U)
re_date = re.compile(r'ДАТА ?[\.:]', re.I | re.U)
re_handout = re.compile(r'РАЗДА(ЧА|ТКА|ТОЧНЫЙ МАТЕРИАЛ) ?[\.:]', re.I | re.U)
re_number = re.compile(r'^[0-9]+[\.\)] *')

##### PDB DEBUGGING
def info(type, value, tb):
   if hasattr(sys, 'ps1') or not sys.stderr.isatty():
      # we are in interactive mode or we don't have a tty-like
      # device, so we call the default hook
      sys.__excepthook__(type, value, tb)
   else:
      import traceback, pdb
      # we are NOT in interactive mode, print the exception...
      traceback.print_exception(type, value, tb)
      print
      # ...then start the debugger in post-mortem mode.
      pdb.pm()

sys.excepthook = info
##### END DEBUGGING

def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0]+indices, indices+[None])]

class Question(object):
    def __init__(self, *args, **kwargs):
        for k, v in kwargs.items():
            if k in QUESTION_LABELS:
                setattr(self, k, v)
            else:
                raise Exception('Unexpected argument: {}'.format(k))
    def __repr__(self):
        return "Question('{}{}')".format(
            self.question[:100], 
            '...' if len(self.question) > 100 else '').encode(
            ENC, errors='replace')

class ParsingStructure(object):
    ### constants
    BADNEXTFIELDS = set(['question', 'answer'])
    regexes = {
        'tour' : re_tour,
        'tourrev' : re_tourrev,
        'question' : re_question,
        'answer' : re_answer,
        'accept' : re_accept,
        'reject' : re_reject,
        'comment' : re_comment,
        'author' : re_author,
        'source' : re_source,
        'editor' : re_editor,
        'date' : re_date,
    }

    ### end constants
    def __init__(self, text):
        """
        Parsing rationale: every Question has two required fields: 'question' 
        and the immediately following 'answer'. All the rest are optional, 
        as is the order of these fields. On the other hand, everything
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
        7. Store the resulting structure as self.structure
        """

        self.structure = []

        # 1.

        for x in re.split(r'\r?\n',text):
            if x != '':
                self.structure.append(['',remove_excessive_whitespace(x)])

        i = 0
        st = self.structure
        while i < len(st):
            matching_regexes = {
                (regex, self.regexes[regex].search(st[i][1]).start(0)) 
                 for regex in self.regexes 
                 if self.regexes[regex].search(st[i][1])}
            
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
                    self.structure.insert(
                        i+1, slice_)
                st[i][0] = sorted_r[0][0]
                st[i][1] = st[i][1][:sorted_r[1][1]]
            i += 1
        self.structure = st
        i = 0
            

        # 2.

        self.merge_y_to_x('question','answer')
        self.merge_to_x_until_nextfield('answer')
        self.merge_to_x_until_nextfield('comment')

        # 3.

        i = 0
        while i < len(self.structure):
            if (self.structure[i][0] == 'answer' 
                and self.structure[i-1][0] not in ('question',
                    'newquestion')):
                self.structure.insert(i,['newquestion',''])
                i = 0
            i += 1
        
        i = 0
        while i < len(self.structure) - 1:
            if (self.structure[i][0] == ''
                and self.structure[i+1][0] == 'newquestion'):
                self.merge_to_next(i)
                if (re_number.search(
                    remove_excessive_whitespace(self.structure[i][1])) 
                and not re_number.search(
                    remove_excessive_whitespace(self.structure[i-1][1]))):
                    self.structure[i][0] = 'question'
                    self.structure[i][1] = re_number.sub(
                        '',remove_excessive_whitespace(self.structure[i][1]))
                    try:
                        self.structure.insert(i, 
                            ['number', int(re_number.search(
                                remove_excessive_whitespace(
                                    self.structure[i][1])
                                ).group(0))])
                    except:
                        pass # TODO: figure out what this means
                i = 0
            i += 1

        for element in self.structure:
            if element[0] == 'newquestion':
                element[0] = 'question'

        self.dirty_merge_to_x_until_nextfield('source')

        for id, element in enumerate(self.structure):
            if (element[0] == 'author' and re.search(r'^{}$'.format(re_author.
                pattern),
                remove_excessive_whitespace(element[1]))
                and id + 1 < len(self.structure)):
                merge_to_previous(id+1)
        
        self.merge_to_x_until_nextfield('accept')
        self.merge_to_x_until_nextfield('reject')
        
        # 4.

        self.structure = [x for x in self.structure if [x[0], remove_excessive_whitespace(x[1])]
            != ['', '']]

        if self.structure[0][0] == '' and re_number.search(
            remove_excessive_whitespace(self.structure[0][1])):
            self.merge_to_next(0)

        for id, element in enumerate(self.structure):
            if element[0] == '':
                element[0] = 'meta'
            if element[0] in self.regexes and element[0] not in ['tour', 'tourrev']:
                if element[0] == 'question':
                    try:
                        num = re_question.search(element[1]).group(1)
                        self.structure.insert(id, ['number', num])
                    except:
                        pass
                element[1] = self.regexes[element[0]].sub('', element[1])

        # 5.

        for id, element in enumerate(self.structure):
            
            # typogrify

            if element[0] != 'date':
                element[1] = recursive_typography(element[1])

            # remove question numbers

            if element[0] == 'question':
                try:
                    num = re_question.search(element[1]).group(1)
                    self.structure.insert(id, ['number', num])
                except:
                    pass
                element[1] = re_number.sub('', element[1])
            
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
                            part[lc+1] = part[lc+1].replace(
                                list_candidate[lc][1], '')
                            lc += 1
                        element[1] = ([part[0], part[1:]] if part[0] != ''
                                                else part[1:])

            # turn source into list if necessary
            if (element[0] == 'source' and isinstance(element[1], basestring)
                        and len(re.split(r'\r?\n', element[1])) > 1):
                element[1] = [re_number.sub('', remove_excessive_whitespace(x)) 
                    for x in re.split(r'\r?\n', element[1])]

        # 6.
        final_structure = []
        current_question = {}

        for element in self.structure:
            if element[0] in set(['tour', 'question', 'meta']): 
                if current_question != {}:
                    self.check_question(current_question)
                    final_structure.append(Question(**current_question))
                    current_question = {}
            if element[0] in QUESTION_LABELS:
                if element[0] in current_question:
                    try:
                        current_question[element[0]] += SEP + element[1]
                    except:
                        print('{}'.format(current_question).decode('unicode_escape'))
                        pdb.set_trace()
                else:
                    current_question[element[0]] = element[1]
            else:
                final_structure.append([element[0], element[1]])
        if current_question != {}:
            self.check_question(current_question)
            final_structure.append(Question(**current_question))

        # 7.
        self.structure = final_structure

    def merge_to_previous(self, index):
        target = index - 1
        self.structure[target][1] = (
            self.structure[target][1] + SEP 
            + self.structure.pop(index)[1])

    def merge_to_next(self, index):
        target = self.structure.pop(index)
        self.structure[index][1] = (target[1] + SEP 
            + self.structure[index][1])

    def find_next_specific_field(self, index, fieldname):
        target = index + 1
        while self.structure[target][0] != fieldname:
            target += 1
        return target

    def find_next_fieldname(self, index):
        target = index + 1
        if target < len(self.structure):
            while (target < len(self.structure)-1
                and self.structure[target][0] == ''):
                target += 1
            return self.structure[target][0]

    def merge_y_to_x(self, x, y):
        i = 0
        while i < len(self.structure):
            if self.structure[i][0] == x:
                while (i+1 < len(self.structure) 
                    and self.structure[i+1][0] != y):
                    self.merge_to_previous(i+1)
            i += 1

    def merge_to_x_until_nextfield(self, x):
        i = 0
        while i < len(self.structure):
            if self.structure[i][0] == x:
                while (i+1 < len(self.structure) 
                    and self.structure[i+1][0] == ''
                    and self.find_next_fieldname(i) 
                        not in self.BADNEXTFIELDS):
                    self.merge_to_previous(i+1)
            i += 1

    def dirty_merge_to_x_until_nextfield(self, x):
        i = 0
        while i < len(self.structure):
            if self.structure[i][0] == x:
                while (i+1 < len(self.structure) 
                    and self.structure[i+1][0] == ''):
                    self.merge_to_previous(i+1)
            i += 1

    def swap_elements(self, x, y):
        z = self.structure[y]
        self.structure[y] = self.structure[x]
        self.structure[x] = z

    def check_question(self, question):
        warnings = []
        for el in {'question', 'answer', 'source', 'author'}:
            if el not in question:
                warnings.append(el)
        if len(warnings) > 1:
            print('WARNING: question {} lacks the following fields: {}{}'
                .format(question, ', '.join(warnings), SEP)
                .decode('unicode_escape')
                .encode(ENC, errors='replace'))

    def __repr__(self):
        '...'
        pass

class Package(object):
    def __init__(self, file=None, string=None):
        if not file is None and not string is None:
            raise Exception('You must specify either '
                'a file or a string, not both.')
        if not string is None:
            '...'
            pass
        if not file is None:
            '...'
            pass
        if file is None and string is None:
            # TODO: sane empty package init code
            self.tours = self._parse()
    
    def _parse(self, string):
        self.tours = ParsingStructure(string).structure

    def __repr__(self):
        '...'
        pass

def main():
    pass

if __name__ == "__main__":
    main()