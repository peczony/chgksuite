#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import re
import codecs
import json
try:
    from urlparse import urljoin
except ImportError:
    from urllib.parse import urljoin
try:
    from urllib import urlretrieve
except ImportError:
    from urllib.request import urlretrieve
import logging

from ply import lex

from typotools import recursive_typography as rt

re_list = re.compile(r'^\s{3}\d+\.\s(.+)$', re.I | re.U)

tokens = (
    'TITLE',
    'URL',
    'DATE',
    'EDITOR',
    'INFO',
    'TOUR',
    'QUESTION',
    'HANDOUT',
    'PIC',
    'ANSWER',
    'ZACHET',
    'NEZACHET',
    'COMMENT',
    'SOURCE',
    'AUTHOR',
    'TEXT'
)

states = (
    ('title', 'exclusive'),
    ('url', 'exclusive'),
    ('date', 'exclusive'),
    ('editor', 'exclusive'),
    ('info', 'exclusive'),
    ('tour', 'exclusive'),
    ('question', 'exclusive'),
    ('handout', 'exclusive'),
    ('pic', 'exclusive'),
    ('answer', 'exclusive'),
    ('zachet', 'exclusive'),
    ('nezachet', 'exclusive'),
    ('comment', 'exclusive'),
    ('source', 'exclusive'),
    ('author', 'exclusive')
)

DB_PIC_BASE_URL = 'http://db.chgk.info/images/db/'
DB_AUD_BASE_URL = 'http://db.chgk.info/sounds/db/'

logger = None


def append_question(lexer):
    if lexer.question:
        # remove empty values
        question = dict((k, v) for k, v in iter(lexer.question.items()) if v)
        lexer.structure.append(['Question', question])


def init_question(lexer):
    # save old values
    append_question(lexer)
    lexer.question_num += 1
    lexer.question = {'number': lexer.question_num,
                      'question': [],
                      'answer': [],
                      'comment': [],
                      'source': []}


def t_TITLE(t):
    r'Чемпионат:\n'
    t.lexer.begin('title')
    t.lexer.text = ''


def t_URL(t):
    r'URL:\n'
    t.lexer.begin('url')
    t.lexer.text = ''


def t_DATE(t):
    r'Дата:\n'
    t.lexer.begin('date')
    t.lexer.text = ''


def t_EDITOR(t):
    r'Редактор:\n'
    t.lexer.begin('editor')
    t.lexer.text = ''


def t_INFO(t):
    r'Инфо:\n'
    t.lexer.begin('info')
    t.lexer.text = ''


def t_TOUR(t):
    r'Тур:\n'
    t.lexer.begin('tour')
    init_question(t.lexer)
    t.lexer.text = ''


def t_QUESTION(t):
    r'Вопрос\s+[\d]+:\n'
    t.lexer.begin('question')
    init_question(t.lexer)
    t.lexer.text = ''


def t_ANSWER(t):
    r'Ответ:\n'
    t.lexer.begin('answer')
    t.lexer.text = ''
    if t.lexer.question['answer']:
        logger.warning("Bad format: several Answer fields. "
                       "Previous Answer was:"
                       " '%s'", t.lexer.question['answer'])


def t_ZACHET(t):
    r'Зачет:\n'
    t.lexer.begin('zachet')
    t.lexer.text = ''


def t_NEZACHET(t):
    r'Незачет:\n'
    t.lexer.begin('nezachet')
    t.lexer.text = ''


def t_COMMENT(t):
    r'Комментарий:\n'
    t.lexer.begin('comment')
    t.lexer.text = ''
    if t.lexer.question['comment']:
        logger.warning("Bad format: several Comment fields. "
                       "Previous Comment was:"
                       " '%s'", t.lexer.question['comment'])


def t_SOURCE(t):
    r'Источник:\n'
    t.lexer.begin('source')
    t.lexer.text = ''
    if t.lexer.question['source']:
        logger.warning("Bad format: several Source fields. "
                       "Previous Source was:"
                       " '%s'", t.lexer.question['source'])


def t_AUTHOR(t):
    r'Автор:\n'
    t.lexer.begin('author')
    t.lexer.text = ''


def t_title_end(t):
    r'\n\n'
    t.lexer.structure.append(['heading', rt(t.lexer.text)])
    t.lexer.structure.append(['ljheading', rt(t.lexer.text)])
    t.lexer.begin('INITIAL')


def t_url_end(t):
    r'\n\n'
    t.lexer.structure.append(['meta', t.lexer.text])
    t.lexer.begin('INITIAL')


def t_date_end(t):
    r'\n\n'
    t.lexer.structure.append(['date', t.lexer.text])
    t.lexer.begin('INITIAL')


def t_info_end(t):
    r'\n\n'
    t.lexer.structure.append(['meta', rt(t.lexer.text)])
    t.lexer.begin('INITIAL')


def t_editor_end(t):
    r'\n\n'
    t.lexer.structure.append(['editor', rt(t.lexer.text)])
    t.lexer.begin('INITIAL')


def t_tour_end(t):
    r'\n\n'
    t.lexer.structure.append(['tour', rt(t.lexer.text)])
    t.lexer.begin('INITIAL')


def t_question_HANDOUT(t):
    r'\s{3}<раздатка>\n'
    t.lexer.text += '[Раздаточный материал:'
    t.lexer.begin('handout')


def t_handout_end(t):
    r'\s{3}</раздатка>\n'
    t.lexer.text += '\n]'
    t.lexer.begin('question')


def t_question_PIC(t):
    r'(?:\((?:img|aud)\s(?:[\d\.\w]+)\)\s*)+\n'
    t.lexer.text += '[Раздаточный материал:%s]' % t.value.strip()


def t_question_TEXT(t):
    r'.+'
    match_list = re_list.search(t.value)
    if match_list:
        if t.lexer.text:
            multi_question_num = len(t.lexer.question['question'])
            if multi_question_num == 0:
                t.lexer.question['question'].append(t.lexer.text)
            elif multi_question_num == 1:
                t.lexer.question['question'].append([])
                t.lexer.question['question'][1].append(t.lexer.text)
            else:
                t.lexer.question['question'][1].append(t.lexer.text)
        t.lexer.text = match_list.group(1)
    else:
        if t.value[0:3] == '   ':
            t.lexer.text += '\n' + t.value[3:]
        else:
            t.lexer.text += t.value


def t_question_end(t):
    r'\n\n'
    if len(t.lexer.question['question']) == 2:
        t.lexer.question['question'][1].append(t.lexer.text)
    else:
        t.lexer.question['question'] = t.lexer.text
    t.lexer.question['question'] = rt(t.lexer.question['question'])
    t.lexer.begin('INITIAL')


def t_answer_TEXT(t):
    r'.+'
    match_list = re_list.search(t.value)
    if match_list:
        if t.lexer.text:
            t.lexer.question['answer'].append(t.lexer.text)
        t.lexer.text = match_list.group(1)
    else:
        if t.value[0:3] == '   ':
            t.lexer.text += '\n' + t.value[3:]
        else:
            t.lexer.text += t.value


def t_answer_end(t):
    r'\n\n'
    if t.lexer.question['answer']:
        if isinstance(t.lexer.question['answer'], list):
            t.lexer.question['answer'].append(t.lexer.text)
        else:
            # bad format: several Answer fields for given question
            t.lexer.question['answer'] += '\n' + t.lexer.text
    else:
        t.lexer.question['answer'] = t.lexer.text
    t.lexer.question['answer'] = rt(t.lexer.question['answer'])
    t.lexer.begin('INITIAL')


def t_zachet_end(t):
    r'\n\n'
    t.lexer.question['zachet'] = rt(t.lexer.text)
    t.lexer.begin('INITIAL')


def t_nezachet_end(t):
    r'\n\n'
    t.lexer.question['nezachet'] = rt(t.lexer.text)
    t.lexer.begin('INITIAL')


def t_comment_TEXT(t):
    r'.+'
    match_list = None

    # check if Comment already started, interpret list items as text
    if isinstance(t.lexer.question['comment'], list):
        match_list = re_list.search(t.value)

    if match_list:
        if t.lexer.text:
            t.lexer.question['comment'].append(t.lexer.text)
        t.lexer.text = match_list.group(1)
    else:
        if isinstance(t.lexer.question['comment'], list) and\
           not t.lexer.question['comment'] and not t.lexer.text:
            # Comment started with some text, interpret it as text
            t.lexer.question['comment'] = ''
        if t.value[0:3] == '   ':
            t.lexer.text += '\n' + t.value[3:]
        else:
            t.lexer.text += t.value


def t_comment_end(t):
    r'\n\n'
    if t.lexer.question['comment']:
        if isinstance(t.lexer.question['comment'], list):
            # multicomment (doublet, blitz, etc.)
            t.lexer.question['comment'].append(t.lexer.text)
        else:
            # bad format: several Comment fields for given question
            t.lexer.question['comment'] += '\n' + t.lexer.text
    else:
        t.lexer.question['comment'] = t.lexer.text
    t.lexer.question['comment'] = rt(t.lexer.question['comment'])
    t.lexer.begin('INITIAL')


def t_source_TEXT(t):
    r'.+'
    match_list = re_list.search(t.value)
    if match_list:
        if not isinstance(t.lexer.question['source'], list):
            # bad format: several Source fields for given question
            t.lexer.question['source'] = [t.lexer.question['source']]

        if t.lexer.text:
            t.lexer.question['source'].append(t.lexer.text)
        t.lexer.text = match_list.group(1)
    else:
        if t.value[0:3] == '   ':
            t.lexer.text += '\n' + t.value[3:]
        else:
            t.lexer.text += t.value


def t_source_end(t):
    r'\n\n'
    if t.lexer.question['source']:
        if isinstance(t.lexer.question['source'], list):
            # list of sources
            t.lexer.question['source'].append(t.lexer.text)
        else:
            # bad format: several Source fields for given question
            t.lexer.question['source'] += '\n' + t.lexer.text
    else:
        t.lexer.question['source'] = t.lexer.text
    t.lexer.question['source'] = rt(t.lexer.question['source'])
    t.lexer.begin('INITIAL')


def t_author_end(t):
    r'\n\n'
    t.lexer.question['author'] = rt(t.lexer.text)
    t.lexer.begin('INITIAL')


def t_ANY_TEXT(t):
    r'.+'
    if t.value[0:3] == '   ':
        # new line start
        t.lexer.text += '\n' + t.value[3:]
    else:
        t.lexer.text += t.value
    return t


def t_ANY_ENDLINE(t):
    r'\n'
    t.lexer.text += ' '


def t_ANY_error(t):
    logger.warning("Illegal character '%s'", t.value[0])
    t.lexer.skip(1)


def replace_handouts(match_handout):
    handout_type = 'img' if match_handout.group(1) == 'pic' else 'aud'
    db_base_url = (DB_PIC_BASE_URL
                   if match_handout.group(1) == 'pic'
                   else DB_AUD_BASE_URL)
    handout_name = match_handout.group(2)
    handout_path = os.path.abspath(handout_name)
    if not os.path.exists(handout_path):
        handout_url = urljoin(db_base_url, handout_name)
        try:
            urlretrieve(handout_url, handout_path)
        except Exception as e:
            logger.warning("Can't get file from %s to %s: %s",
                           handout_url, handout_path, str(e))
    return '(%s %s)' % (handout_type, handout_name)


def chgk_parse_db(text, debug=False):
    global logger

    if not logger:
        logger = logging.getLogger('parser_db')
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler('parser_db.log')
        fh.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        if debug:
            ch.setLevel(logging.INFO)
        else:
            ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s: %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(ch)

    re_handout = re.compile(r'\((pic|aud):\s([\d\.\w]+)\)', re.I | re.U)
    text = re_handout.sub(replace_handouts, text)

    lexer = lex.lex(reflags=re.I | re.U)
    lexer.text = ''
    lexer.structure = []
    lexer.question_num = 0
    lexer.question = {}
    lexer.input(text)
    for _ in iter(lexer.token, None):
        pass

    # save last question
    append_question(lexer)

    if debug:
        with codecs.open('debug_final.json', 'w', 'utf8') as f:
            f.write(json.dumps(lexer.structure, ensure_ascii=False, indent=4))

    return lexer.structure


def main():
    print('This program was not designed to run standalone.')
    try:
        raw_input("Press Enter to continue...")
    except NameError:
        input("Press Enter to continue...")

if __name__ == "__main__":
    main()
