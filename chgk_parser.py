#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import argparse
import pprint
import urllib
import re
import os
import pdb
import sys
import chardet
import codecs
import json
import typotools
import traceback
import subprocess
import shlex
import datetime
from pydocx import PyDocX
from bs4 import BeautifulSoup
from parse import parse
import base64
import html2text
from typotools import remove_excessive_whitespace as rew

try:
    from Tkinter import *
except:
    from tkinter import *
import tkFileDialog

debug = False
console_mode = False

QUESTION_LABELS = ['handout', 'question', 'answer',
        'zachet', 'nezachet', 'comment', 'source', 'author', 'number',
        'setcounter']
ENC = ('utf8' if sys.platform != 'win32' else 'cp1251')
CONSOLE_ENC = (ENC if sys.platform != 'win32' else 'cp866')
SEP = os.linesep
EDITORS = {
    'win32': 'notepad',
    'linux2': 'gedit',
    'darwin': 'open -t'
}
TEXTEDITOR = EDITORS[sys.platform]
SOURCEDIR = os.path.dirname(os.path.abspath(__file__))
TARGETDIR = os.getcwd()

def make_filename(s):
    return os.path.splitext(os.path.basename(s))[0]+'.4s'

def debug_print(s):
    if debug == True:
        sys.stderr.write(s+SEP)

def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0]+indices, indices+[None])]

def check_question(question):
    warnings = []
    for el in {'question', 'answer', 'source', 'author'}:
        if el not in question:
            warnings.append(el)
    if len(warnings) > 1:
        print('WARNING: question {} lacks the following fields: {}{}'
            .format(question, ', '.join(warnings), SEP)
            .decode('unicode_escape')
            .encode(CONSOLE_ENC, errors='replace'))

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

    WHITESPACE = set([' ', ' ', '\n', '\r'])
    PUNCTUATION = set([',', '.', ':', ';', '?', '!'])

    re_tour = re.compile(r'^ТУР ?([0-9IVXLCDM]*)([\.:])?$', re.I | re.U)
    re_tourrev = re.compile(r'^([0-9]+) ТУР([\.:])?$', re.I | re.U)
    re_question = re.compile(r'ВОПРОС ?[№N]?([0-9]*) ?[\.:]', re.I | re.U)
    re_answer = re.compile(r'ОТВЕТЫ? ?[№N]?([0-9]+)? ?[:]', re.I | re.U)
    re_zachet = re.compile(r'ЗАЧ[ЕЁ]Т ?[\.:]', re.I | re.U)
    re_nezachet = re.compile(r'НЕЗАЧ[ЕЁ]Т ?[\.:]', re.I | re.U)
    re_comment = re.compile(r'КОММЕНТАРИ[ИЙ] ?[№N]?([0-9]+)? ?[\.:]', re.I | re.U)
    re_author = re.compile(r'АВТОР\(?Ы?\)? ?[\.:]', re.I | re.U)
    re_source = re.compile(r'ИСТОЧНИК\(?И?\)? ?[\.:]', re.I | re.U)
    re_editor = re.compile(r'РЕДАКТОР(Ы|СКАЯ ГРУППА)? ?[\.:]', re.I | re.U)
    re_date = re.compile(r'ДАТА ?[\.:]', re.I | re.U)
    re_handout = re.compile(r'РАЗДА(ЧА|ТКА|ТОЧНЫЙ МАТЕРИАЛ) ?[\.:]', re.I | re.U)
    re_number = re.compile(r'^[0-9]+[\.\)] *')

    regexes = {
        'tour' : re_tour,
        'tourrev' : re_tourrev,
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
        if chgk_parse.structure[target][1]:
            chgk_parse.structure[target][1] = (
                chgk_parse.structure[target][1] + SEP 
                + chgk_parse.structure.pop(index)[1])
        else:
            chgk_parse.structure[target][1] = chgk_parse.structure.pop(
                index)[1]

    def merge_to_next(index):
        target = chgk_parse.structure.pop(index)
        chgk_parse.structure[index][1] = (target[1] + SEP 
            + chgk_parse.structure[index][1])

    def find_next_specific_field(index, fieldname):
        target = index + 1
        while chgk_parse.structure[target][0] != fieldname:
            target += 1
        return target

    def find_next_fieldname(index):
        target = index + 1
        if target < len(chgk_parse.structure):
            debug_print(pprint.pformat(
                chgk_parse.structure[target]))
            while (target < len(chgk_parse.structure)-1
                and chgk_parse.structure[target][0] == ''):
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

    def dirty_merge_to_x_until_nextfield(x):
        i = 0
        while i < len(chgk_parse.structure):
            if chgk_parse.structure[i][0] == x:
                while (i+1 < len(chgk_parse.structure) 
                    and chgk_parse.structure[i+1][0] == ''):
                    merge_to_previous(i+1)
            i += 1

    def swap_elements(x, y):
        z = chgk_parse.structure[y]
        chgk_parse.structure[y] = chgk_parse.structure[x]
        chgk_parse.structure[x] = z

    # 1.

    for x in re.split(r'\r?\n',text):
        if x != '':
            chgk_parse.structure.append(['',rew(x)])

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

    if debug:
        with codecs.open('debug_1.json', 'w', 'utf8') as f:
            f.write(json.dumps(chgk_parse.structure, ensure_ascii=False,
                indent=4))

    # 2.

    merge_y_to_x('question','answer')
    merge_to_x_until_nextfield('answer')
    merge_to_x_until_nextfield('comment')

    if debug:
        with codecs.open('debug_2.json', 'w', 'utf8') as f:
            f.write(json.dumps(chgk_parse.structure, ensure_ascii=False,
                indent=4))

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
            if (re_number.search(
                            rew(chgk_parse.structure[i][1])) and
            not re_number.search(
                rew(chgk_parse.structure[i-1][1]))):
                chgk_parse.structure[i][0] = 'question'
                chgk_parse.structure[i][1] = re_number.sub('',rew(
                    chgk_parse.structure[i][1]))
                try:
                    chgk_parse.structure.insert(i, ['number', int(re_number.search(
                            rew(chgk_parse.structure[i][1])).group(0))])
                except:
                    pass
            i = 0
        i += 1

    for element in chgk_parse.structure:
        if element[0] == 'newquestion':
            element[0] = 'question'

    dirty_merge_to_x_until_nextfield('source')

    for id, element in enumerate(chgk_parse.structure):
        if (element[0] == 'author' and re.search(r'^{}$'.format(re_author.
            pattern),
            rew(element[1]))
            and id + 1 < len(chgk_parse.structure)):
            merge_to_previous(id+1)
    
    merge_to_x_until_nextfield('zachet')
    merge_to_x_until_nextfield('nezachet')

    if debug:
        with codecs.open('debug_3.json', 'w', 'utf8') as f:
            f.write(json.dumps(chgk_parse.structure, ensure_ascii=False,
                indent=4))
    
    # 4.

    chgk_parse.structure = [x for x in chgk_parse.structure if [x[0], rew(x[1])]
        != ['', '']]

    if chgk_parse.structure[0][0] == '' and re_number.search(
        rew(chgk_parse.structure[0][1])):
        merge_to_next(0)

    for id, element in enumerate(chgk_parse.structure):
        if element[0] == '':
            element[0] = 'meta'
        if element[0] in regexes and element[0] not in ['tour', 'tourrev',
            'editor']:
            if element[0] == 'question':
                try:
                    num = re_question.search(element[1]).group(1)
                    chgk_parse.structure.insert(id, ['number', num])
                except:
                    pass
            element[1] = regexes[element[0]].sub('', element[1])
            if element[1].startswith(SEP):
                element[1] = element[1][len(SEP):]

    if debug:
        with codecs.open('debug_4.json', 'w', 'utf8') as f:
            f.write(json.dumps(chgk_parse.structure, ensure_ascii=False,
                indent=4))

    # 5.

    for id, element in enumerate(chgk_parse.structure):
        
        # typogrify

        if element[0] != 'date':
            element[1] = typotools.recursive_typography(element[1])

        # remove question numbers

        if element[0] == 'question':
            try:
                num = re_question.search(element[1]).group(1)
                chgk_parse.structure.insert(id, ['number', num])
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
                        part[lc+1] = part[lc+1].replace(list_candidate[lc][1], '')
                        lc += 1
                    element[1] = ([part[0], part[1:]] if part[0] != ''
                                            else part[1:])

        # turn source into list if necessary

        if (element[0] == 'source' and isinstance(element[1], basestring)
                    and len(re.split(r'\r?\n', element[1])) > 1):
            element[1] = [re_number.sub('', rew(x)) 
                for x in re.split(r'\r?\n', element[1])]

    if debug:
        with codecs.open('debug_5.json', 'w', 'utf8') as f:
            f.write(json.dumps(chgk_parse.structure, ensure_ascii=False,
                indent=4))


    # 6.

    final_structure = []
    current_question = {}

    for element in chgk_parse.structure:
        if (element[0] in set(['number', 'tour', 'question', 'meta'])
            and 'question' in current_question):
                check_question(current_question)
                final_structure.append(['Question', current_question])
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
        check_question(current_question)
        final_structure.append(['Question', current_question])


    # 7.
    if debug:
        with codecs.open('debug_final.json', 'w', 'utf8') as f:
            f.write(json.dumps(final_structure, ensure_ascii=False,
                indent=4))
    return final_structure

class UnknownEncodingException(Exception): pass

def chgk_parse_txt(txtfile, encoding=None):
    os.chdir(os.path.dirname(os.path.abspath(txtfile)))
    raw = open(txtfile,'r').read()
    if not encoding and chardet.detect(raw)['confidence'] > 0.8:
        encoding = chardet.detect(raw)['encoding']
    else:
        raise UnknownEncodingException(
            'Encoding of file {} cannot be verified, '
            'please pass encoding directly via command line '
            'or resave with a less exotic encoding'.format(txtfile))
    text = raw.decode(encoding)
    return chgk_parse(text)

def generate_imgname(ext):
    imgcounter = 1
    while os.path.isfile('{:03}.{}'
        .format(imgcounter, ext)):
        imgcounter += 1
    return '{:03}.{}'.format(imgcounter, ext)

def chgk_parse_docx(docxfile):
    os.chdir(os.path.dirname(os.path.abspath(docxfile)))
    input_docx = PyDocX.to_html(docxfile)
    bsoup = BeautifulSoup(input_docx)

    if debug:
        with codecs.open('debug.pydocx', 'w', 'utf8') as dbg:
            dbg.write(input_docx)
    
    for tag in bsoup.find_all('style'):
        tag.extract()
    for tag in bsoup.find_all('p'):
        if tag.string:
            tag.string = tag.string + SEP
    for tag in bsoup.find_all('b'):
        tag.unwrap()
    for tag in bsoup.find_all('strong'):
        tag.unwrap()
    for tag in bsoup.find_all('i'):
        tag.string = '_' + tag.string + '_'
        tag.unwrap()
    for tag in bsoup.find_all('em'):
        tag.string = '_' + tag.string + '_'
        tag.unwrap()
    for tag in bsoup.find_all('li'):
        if tag.string:
            tag.string = '- ' + tag.string
    for tag in bsoup.find_all('img'):
        imgparse = parse('data:image/{ext};base64,{b64}', tag['src'])
        imgname = generate_imgname(imgparse['ext'])
        with open(imgname, 'wb') as f:
            f.write(base64.b64decode(imgparse['b64']))
        imgpath = os.path.abspath(imgname)
        tag.insert_before('(img {})'.format(imgpath))
        tag.extract()
    for tag in bsoup.find_all('a'):
        if rew(tag.string) == '':
            tag.extract()
        else:
            tag.string = tag['href']
            tag.unwrap()

    h = html2text.HTML2Text()
    h.body_width = 0
    txt = (h.handle(bsoup.prettify())
        .replace('\\-','')
        .replace('\\.','.')
        .replace('( ', '(')
        .replace('[ ', '[')
        .replace(' )', ')')
        .replace(' ]', ']')
        .replace(' :', ':')
        )

    if debug:
        with codecs.open('debug.debug', 'w', 'utf8') as dbg:
            dbg.write(txt)

    final_structure = chgk_parse(txt)
    return final_structure

def remove_double_separators(s):
    return re.sub(r'({})+'.format(SEP), SEP, s)

def compose_4s(structure):
    types_mapping = {
        'meta' : '# ',
        'tour' : '## ',
        'tourrev' : '## ',
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
            return remove_double_separators(z)
        elif isinstance(z, list):
            if isinstance(z[1], list):
                return (remove_double_separators(z[0]) + '- ' + SEP 
                    + ('{}- '.format(SEP)).join((
                        [remove_double_separators(x) for x in z[1]])))
            else:
                return SEP + '- ' + ('{}- '.format(SEP)).join(
                    [remove_double_separators(x) for x in z])
    result = ''
    for element in structure:
        if element[0] in ['tour', 'tourrev']:
            checkNumber = True
        if element[0] == 'number' and checkNumber and int(element[1])!=0:
            checkNumber = False
            result += '№№ '+element[1]+SEP
        if element[0] == 'number' and int(element[1])==0:
            result += '№ '+element[1]+SEP
        if element[0] in types_mapping and types_mapping[element[0]]:
            result += (types_mapping[element[0]] 
                + format_element(element[1]) + SEP + SEP)
        elif element[0] == 'Question':
            for label in QUESTION_LABELS:
                if label in element[1] and label in types_mapping:
                    result += (types_mapping[label]
                        + format_element(element[1][label]) + SEP)
            result += SEP
    return result

def gui_parse(args):

    global console_mode
    global __file__                         # to fix stupid
    __file__ = os.path.abspath(__file__)    # __file__ handling
    _file_ = os.path.basename(__file__)     # in python 2

    global debug

    root = Tk()
    root.withdraw()

    sys.stderr = codecs.getwriter('utf8')(sys.stderr)

    if args.debug:
        debug = True

    if args.filename:
        console_mode = True

    if args.filename is None:
        args.filename = tkFileDialog.askopenfilename(
            filetypes=[
            ('chgksuite parsable files',('*.docx','*.txt'))
            ])
    if not args.filename:
        print('No file specified.')
        sys.exit(0)

    os.chdir(os.path.dirname(os.path.abspath(args.filename)))

    if os.path.splitext(args.filename)[1] == '.txt':
        final_structure = chgk_parse_txt(args.filename)


    elif os.path.splitext(args.filename)[1] == '.docx':
        final_structure = chgk_parse_docx(args.filename)

    else:
        sys.stderr.write('Error: unsupported file format.' + SEP)
        sys.exit()

    outfilename = make_filename(args.filename)
    print('Output: {}'.format(
            os.path.abspath(outfilename)))
    with codecs.open(
        outfilename, 'w', 'utf8') as output_file:
        output_file.write(
            compose_4s(final_structure))

    print('Please review the resulting file {}:'.format(
        make_filename(args.filename)))
    subprocess.call(shlex.split('{} "{}"'
        .format(
            TEXTEDITOR,
            make_filename(args.filename)).encode(ENC,errors='replace')))
    if not console_mode:
        raw_input("Press Enter to continue...")

def main():
    print('This program was not designed to run standalone.')
    raw_input("Press Enter to continue...")

if __name__ == "__main__":
    main()