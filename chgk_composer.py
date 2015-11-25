#!usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
from chgk_parser import QUESTION_LABELS
from docx import Document
from docx.shared import Inches
from parse import parse
from typotools import remove_excessive_whitespace as rew
from xmlrpclib import ServerProxy
from PIL import Image
import argparse
import base64
import codecs
import contextlib
import datetime
import docx
import hashlib
import json
import os
import pdb
import pprint
import pyimgur
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import traceback
import typotools
import urllib

args = None
try:
    from Tkinter import Tk, Frame, IntVar, Button, Checkbutton, Entry, Label
except:
    from tkinter import Tk, Frame, IntVar, Button, Checkbutton, Entry, Label
import tkFileDialog

im = None
debug = False
console_mode = False
re_url = re.compile(r"""((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]"""
"""|[a-z0-9.\-]+[.‌​][a-z]{2,4}/)(?:[^\s<>]+|(([^\s()<>]+|(([^\s<>]+)))*))+"""
"""(?:(([^\s<>]+|(‌​([^\s<>]+)))*)|[^\s`!\[\]{};:'".,<>?«»“”‘’]))""", re.DOTALL)
re_perc = re.compile(r'(%[0-9a-fA-F]{2})+')
re_scaps = re.compile(r'(^|[\s])([«»А-Я `ЁA-Z]{2,})([\s,!\.;:-\?]|$)')
re_em = re.compile(r'_(.+?)_')
re_lowercase = re.compile(r'[а-яё]')
re_uppercase = re.compile(r'[А-ЯЁ]')

REQUIRED_LABELS = set(['question', 'answer'])
SOURCEDIR = os.path.dirname(os.path.abspath(__file__))
TARGETDIR = os.getcwd()

FIELDS = {
    'zachet': 'Зачёт: ',
    'nezachet': 'Незачёт: ',
    'comment': 'Комментарий: ',
    'source': 'Источник: ',
    'author': 'Автор: ',
}

WHITEN = {
    'handout': False,
    'zachet': True,
    'nezachet': True,
    'comment': True,
    'source': True,
    'author': False,
}

def make_filename(s, ext):
    now = datetime.datetime.now()
    bn = os.path.basename(s)
    return (os.path.splitext(bn)[0]+'-{}-{}.'
        .format(now.strftime('%Y%m%d'),
            now.strftime('%H%M'))
        +ext)

@contextlib.contextmanager
def make_temp_directory(**kwargs):
    temp_dir = tempfile.mkdtemp(**kwargs)
    yield temp_dir
    shutil.rmtree(temp_dir)

def proportional_resize(tup):
    if max(tup) > 600:
        return tuple([int(x * 600/max(tup)) for x in tup])
    if max(tup) < 200:
        return tuple([int(x * 200/max(tup)) for x in tup])
    return tup

def imgsize(imgfile, dimensions='pixels', emsize=25, dpi=120):
    img = Image.open(imgfile)
    width, height = proportional_resize((img.width, img.height))
    if dimensions == 'ems':
        return width/emsize, height/emsize
    if dimensions == 'inches':
        return width/dpi, height/dpi
    if dimensions == 'pixels':
        return width, height
    return width, height

def parseimg(s, dimensions='pixels'):
    width = -1
    height = -1
    sp = s.split()
    imgfile = sp[-1]
    if not os.path.isabs(imgfile): 
        if os.path.isfile(
        os.path.join(TARGETDIR, imgfile)):
            imgfile = os.path.join(TARGETDIR, imgfile)
        else:
            imgfile = os.path.join(SOURCEDIR, imgfile)

    if len(sp) == 1:
        width, height = imgsize(imgfile, dimensions=dimensions)
        return imgfile.replace('\\','/'), width, height
    else:
        for spsp in sp[:-1]:
            spspsp = spsp.split('=')
            if spspsp[0] == 'w':
                width = spspsp[1]
            if spspsp[0] == 'h':
                height = spspsp[1]
        return imgfile.replace('\\','/'), width, height

def debug_print(s):
    if debug == True:
        sys.stderr.write(s+'\n')

def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0]+indices, indices+[None])]



def parse_4s_elem(s):
    
    def find_next_unescaped(ss, index):
        j = index + 1
        while j < len(ss):
            if ss[j] == '\\' and j+2 < len(ss):
                j += 2
            if ss[j] == ss[index]:
                return j
            j += 1
        return -1

    for gr in re_url.finditer(s):
        gr0 = gr.group(0)
        s = s.replace(gr0, gr0.replace('_', '\\_'))

    # for gr in re_scaps.finditer(s):
    #     gr0 = gr.group(0)
    #     s = s.replace(gr0, '(sc '+gr0.lower()+')')

    grs = sorted([match.group(0) 
        for match in re_perc.finditer(s)], key=len, reverse=True)
    for gr in grs:
        try:
            s = s.replace(gr,urllib.unquote(gr.encode('utf8')).decode('utf8'))
        except:
            debug_print('error decoding on line {}: {}\n'
                .format(gr, traceback.format_exc()))
    
    s = list(s)
    i = 0
    topart = []
    while i < len(s):
        if s[i] == '_' and (i == 0 or s[i-1] != '\\'):
            debug_print('found _ at {} of line {}'
                .format(i, s))
            topart.append(i)
            if find_next_unescaped(s, i) != -1:
                topart.append(find_next_unescaped(s, i)+1)
                i = find_next_unescaped(s, i) + 2
                continue
        if (s[i] == '(' and i + len('(img') < len(s) and ''.join(s[i:
                            i+len('(img')])=='(img'):
            debug_print('img candidate')
            topart.append(i)
            if not typotools.find_matching_closing_bracket(s, i) is None:
                topart.append(
                    typotools.find_matching_closing_bracket(s, i)+1)
                i = typotools.find_matching_closing_bracket(s, i)+2
        # if (s[i] == '(' and i + len('(sc') < len(s) and ''.join(s[i:
        #                     i+len('(sc')])=='(sc'):
        #     debug_print('sc candidate')
        #     topart.append(i)
        #     if not typotools.find_matching_closing_bracket(s, i) is None:
        #         topart.append(
        #             typotools.find_matching_closing_bracket(s, i)+1)
        #         i = typotools.find_matching_closing_bracket(s, i)+2
        i += 1

    topart = sorted(topart)

    parts = [['', ''.join(x)] for x in partition(s, topart)]
    debug_print(pprint.pformat(parts).decode('unicode_escape'))

    for part in parts:
        if part == ['', '']:
            continue
        try:
            if part[1][-1] == '_':
                part[1] = part[1][1:]
                part[0] = 'em'
            if part[1][-1] == '_':
                part[1] = part[1][:-1]
                part[0] = 'em'
            if len(part[1]) > 4 and part[1][:4] == '(img':
                if part[1][-1] != ')':
                    part[1] = part[1] + ')'
                part[1] = typotools.remove_excessive_whitespace(
                    part[1][4:-1])
                part[0] = 'img'
                debug_print('found img at {}'
                    .format(pprint.pformat(part[1])))
            if len(part[1]) > 3 and part[1][:4] == '(sc':
                if part[1][-1] != ')':
                    part[1] = part[1] + ')'
                part[1] = typotools.remove_excessive_whitespace(
                    part[1][3:-1])
                part[0] = 'sc'
                debug_print('found img at {}'
                    .format(pprint.pformat(part[1])))
            part[1] = part[1].replace('\\_', '_')
        except:
            sys.stderr.write('Error on part {}: {}'
                .format(pprint.pformat(part).decode('unicode_escape'),
                traceback.format_exc() ))

    return parts

def parse_4s(s, randomize=False):
    mapping = {
        '#' : 'meta',
        '##' : 'section',
        '###' : 'heading',
        '###LJ': 'ljheading',
        '#EDITOR': 'editor',
        '#DATE': 'date',
        '?': 'question',
        '№': 'number',
        '№№': 'setcounter',
        '!': 'answer',
        '=': 'zachet',
        '!=': 'nezachet',
        '^': 'source',
        '/': 'comment',
        '@': 'author',
        '>': 'handout',
    }

    structure = []

    if s[0] == '\ufeff' and len(s) > 1:
        s = s[1:]

    with codecs.open('raw.debug', 'w', 'utf8') as debugf:
        debugf.write(pprint.pformat(s.split('\n')).decode('unicode_escape'))
    
    for line in s.split('\n'):
        if rew(line) == '':
            structure.append(['', ''])
        else:
            if line.split()[0] in mapping:
                structure.append([mapping[line.split()[0]], 
                    rew(line[
                        len(line.split()[0]):])])
            else:
                if len(structure) >= 1:
                    structure[len(structure)-1][1] += '\n' + line

    final_structure = []
    current_question = {}
    counter = 1

    if debug:
        with codecs.open('debug1st.debug', 'w', 'utf8') as debugf:
            debugf.write(pprint.pformat(structure).decode('unicode_escape'))

    for element in structure:
        
        # find list in element

        sp = element[1].split('\n')
        if len(sp) > 1:
            list_candidate = []
            
            for line in sp:
                if len(rew(line).split())>1 and rew(line).split()[0] == '-':
                    list_candidate.append(
                        rew(
                            rew(
                            line
                            )[1:]
                        ))
            
            sp = [spsp for spsp in sp if rew(rew(spsp)[1:]) not in list_candidate]
            
            if len(sp) == 0 or len(sp) == 1 and sp[0] == '':
                element[1] = list_candidate
            else:
                element[1] = (['\n'.join(sp), list_candidate] 
                    if len(list_candidate)>1 
                    else '\n'.join(element[1].split('\n')))

        if element[0] in QUESTION_LABELS:
            if element[0] in current_question:
                
                if (isinstance(current_question[element[0]], basestring)
                    and isinstance(element[1], basestring)):
                    current_question[element[0]] += '\n' + element[1]
                
                elif (isinstance(current_question[element[0]], list)
                    and isinstance(element[1], basestring)):
                    current_question[element[0]][0] += '\n' + element[1]
                
                elif (isinstance(current_question[element[0]], basestring)
                    and isinstance(element[1], list)):
                    current_question[element[0]] = [element[1][0] + '\n'
                        + current_question[element[0]], element[1][1]]
                
                elif (isinstance(current_question[element[0]], list)
                    and isinstance(element[1], list)):
                    current_question[element[0]][0] += '\n' + element[1][0]
                    current_question[element[0]][1] += element[1][1]
            else:
                current_question[element[0]] = element[1]
        
        elif element[0] == '':
            
            if current_question != {}:
                assert all(True for label in REQUIRED_LABELS 
                    if label in current_question)
                if 'setcounter' in current_question:
                    counter = int(current_question['setcounter'])
                if not 'number' in current_question:
                    current_question['number'] = counter
                    counter += 1
                final_structure.append(['Question', current_question])
            
            current_question = {}

        else:
            final_structure.append([element[0], element[1]])
    
    if current_question != {}:
        assert all(True for label in REQUIRED_LABELS 
                if label in current_question)
        if 'setcounter' in current_question:
            counter = int(current_question['setcounter'])
        if not 'number' in current_question:
            current_question['number'] = counter
            counter += 1
        final_structure.append(['Question', current_question])

    if randomize:
        random.shuffle(final_structure, lambda: 0.3)
        i = 1
        for element in final_structure:
            if element[0] == 'Question':
                element[1]['number'] = i
                i += 1

    if debug:
        with codecs.open('debug.debug', 'w', 'utf8') as debugf:
            debugf.write(pprint.pformat(final_structure))

    return final_structure


def gui_get_filetype():
    ch_spoilers = IntVar()
    ch_answers = IntVar()
    if args.nospoilers:
        ch_spoilers.set(0)
    else:
        ch_spoilers.set(1)
    root = Tk()
    frame = Frame(root)
    frame.pack()
    bottomframe = Frame(root)
    bottomframe.pack(side = 'bottom')
    def docxreturn():
        root.ret = 'docx', ch_spoilers.get(), ch_answers.get()
        root.quit()
        root.destroy()
    def texreturn():
        root.ret = 'tex', ch_spoilers.get(), ch_answers.get()
        root.quit()
        root.destroy()
    def ljreturn():
        root.ret = 'lj', ch_spoilers.get(), ch_answers.get()
        root.quit()
        root.destroy()
    def chtoggle():
        if ch_spoilers.get() == 0:
            ch_spoilers.set(1)
        else:
            ch_spoilers.set(0)
    def antoggle():
        if ch_answers.get() == 0:
            ch_answers.set(1)
        else:
            ch_answers.set(0)
    Button(frame, command=
        docxreturn, text = 'docx').pack(side = 'left')
    Button(frame, command=
        texreturn, text = 'tex').pack(side = 'left')
    Button(frame, command=
        ljreturn, text = 'LJ').pack(side = 'left')
    ch = Checkbutton(bottomframe, text='Spoilers',
        variable=ch_spoilers, command=chtoggle)
    ans = Checkbutton(bottomframe, text='No answers',
        variable=ch_answers, command=antoggle)
    if ch_spoilers.get() == 1:
        ch.select()
    if ch_answers.get() == 1:
        ans.select()
    ch.pack(side = 'bottom')
    ans.pack(side = 'bottom')
    root.mainloop()
    return root.ret

def docx_format(el, para, whiten):
    if isinstance(el, list):
        
        if len(el) > 1 and isinstance(el[1], list):
            docx_format(el[0], para, whiten)
            licount = 0
            for li in el[1]:
                licount += 1
                
                p = gui_compose.doc.add_paragraph('{}. '
                    .format(licount))
                docx_format(li, p, whiten)
        else:
            licount = 0
            for li in el:
                licount += 1
                
                p = gui_compose.doc.add_paragraph('{}. '
                    .format(licount))
                docx_format(li, p, whiten)

    if isinstance(el, basestring):
        debug_print('parsing element {}:'
            .format(pprint.pformat(el).decode('unicode_escape')))

        while '`' in el:
            if el.index('`') + 1 >= len(el):
                el = el.replace('`', '')
            else:
                if (el.index('`')+2 < len(el) 
                    and re.search(r'\s', el[el.index('`')+2])):
                    el = el[:el.index('`')+2]+''+el[el.index('`')+2:]
                if (el.index('`')+1 < len(el) 
                    and re_lowercase.search(el[el.index('`')+1])):
                    el = (el[:el.index('`')+1]+''
                        +el[el.index('`')+1]+'\u0301'+el[el.index('`')+2:])
                elif (el.index('`')+1 < len(el) 
                    and re_uppercase.search(el[el.index('`')+1])):
                    el = (el[:el.index('`')+1]+''
                        +el[el.index('`')+1]+'\u0301'+el[el.index('`')+2:])
                el = el[:el.index('`')]+el[el.index('`')+1:]
        parsed = parse_4s_elem(el)
        images_exist = False
        
        for run in parsed:
            if run[0] == 'img':
                images_exist = True
        
        for run in parse_4s_elem(el):
            if run[0] == '':
                r = para.add_run(run[1])
                if whiten and not args.nospoilers:
                    r.style = 'Whitened'
                if images_exist:
                    para = gui_compose.doc.add_paragraph()
            
            elif run[0] == 'em':
                r = para.add_run(run[1])
                r.italic = True
                if whiten and not args.nospoilers:
                    r.style = 'Whitened'
                if images_exist:
                    para = gui_compose.doc.add_paragraph()

            elif run[0] == 'sc':
                r = para.add_run(run[1])
                r.small_caps = True
                if whiten and not args.nospoilers:
                    r.style = 'Whitened'
                if images_exist:
                    para = gui_compose.doc.add_paragraph()
            
            elif run[0] == 'img':
                imgfile, width, height = parseimg(run[1], dimensions='inches')
                gui_compose.doc.add_picture(imgfile, width=Inches(width),
                    height=Inches(height))
                para = gui_compose.doc.add_paragraph()

def html_format_question(q):
    yapper = htmlyapper
    if 'setcounter' in q:
        gui_compose.counter = int(q['setcounter'])
    res = (
    '<strong>Вопрос {}.</strong> {}'.format(gui_compose.counter 
        if not 'number' in q else q['number'], yapper
        (q['question'])
        +('\n<lj-spoiler>' if not args.nospoilers else '')))
    if not 'number' in q:
        gui_compose.counter += 1
    res += '\n<strong>Ответ: </strong>{}'.format(
        yapper(q['answer']),
        )
    if 'zachet' in q:
        res += '\n<strong>Зачёт: </strong>{}'.format(
        yapper(q['zachet']),
        )
    if 'nezachet' in q:
        res += '\n<strong>Незачёт: </strong>{}'.format(
        yapper(q['nezachet']),
        )
    if 'comment' in q:
        res += '\n<strong>Комментарий: </strong>{}'.format(
        yapper(q['comment']),
        )
    if 'source' in q:
        res += '\n<strong>Источник{}: </strong>{}'.format(
        'и' if isinstance(q['source'], list) else '',
        yapper(q['source']),
        )
    if 'author' in q:
        res += '\n<strong>Автор{}: </strong>{}'.format(
        'ы' if isinstance(q['author'], list) else '',
        yapper(q['author']))
    if not args.nospoilers:
        res += '</lj-spoiler>'
    return res

def htmlrepl(zz):
    zz = zz.replace('&','&amp;')
    zz = zz.replace('<','&lt;')
    zz = zz.replace('>','&gt;')
    
    # while re_scaps.search(zz):
    #     zz = zz.replace(re_scaps.search(zz).group(1),
    #         '\\tsc{'+re_scaps.search(zz).group(1).lower()+'}')
    
    while '`' in zz:
        if zz.index('`') + 1 >= len(zz):
            zz = zz.replace('`', '')
        else:
            if (zz.index('`')+2 < len(zz) 
                and re.search(r'\s', zz[zz.index('`')+2])):
                zz = zz[:zz.index('`')+2]+''+zz[zz.index('`')+2:]
            if (zz.index('`')+1 < len(zz) 
                and re_lowercase.search(zz[zz.index('`')+1])):
                zz = (zz[:zz.index('`')+1]+''
                    +zz[zz.index('`')+1]+'&#x0301;'+zz[zz.index('`')+2:])
            elif (zz.index('`')+1 < len(zz) 
                and re_uppercase.search(zz[zz.index('`')+1])):
                zz = (zz[:zz.index('`')+1]+''
                    +zz[zz.index('`')+1]+'&#x0301;'+zz[zz.index('`')+2:])
            zz = zz[:zz.index('`')]+zz[zz.index('`')+1:]

    return zz

def htmlformat(s):
    res = ''
    for run in parse_4s_elem(s):
        if run[0] == '':
            res += htmlrepl(run[1])
        if run[0] == 'em':
            res += '<em>'+htmlrepl(run[1])+'</em>'
        if run[0] == 'img':
            imgfile, w, h = parseimg(run[1])
            if os.path.isfile(imgfile):
                # with open(imgfile, 'rb') as f:
                #     imgdata = f.read()
                # imgfile = 'data:image/{ext};base64,{b64}'.format(
                #     ext=os.path.splitext(imgfile)[-1][1:], 
                #     b64=base64.b64encode(imgdata))
                uploaded_image = im.upload_image(imgfile, 
                    title=imgfile)
                imgfile = uploaded_image.link

            res += '<img{}{} src="{}"/>'.format(
                '' if w==-1 else ' width={}'.format(w),
                '' if h==-1 else ' height={}'.format(h),
                imgfile
                 )
    return res

def htmlyapper(e):
    if isinstance(e, basestring):
        return html_element_layout(e)
    elif isinstance(e, list):
        if not any(isinstance(x, list) for x in e):
            return html_element_layout(e)
        else:
            return '\n'.join([html_element_layout(x) for x in e])

def html_element_layout(e):
    res = ''
    if isinstance(e, basestring):
        res = htmlformat(e)
        return res
    if isinstance(e, list):
        res = '\n'.join(
['{}. {}'.format(en+1, html_element_layout(x)) for en, x in enumerate(e)])
        return res

def md5(s):
    return hashlib.md5(s).hexdigest()

def get_chal(lj, passwd):
    chal = lj.getchallenge()['challenge']
    response = md5(chal + md5(passwd))
    return (chal,response)

def lj_post(stru, passwd):

    lj = ServerProxy('http://www.livejournal.com/interface/xmlrpc').LJ.XMLRPC
     
    chal, response = get_chal(lj, passwd)

    now = datetime.datetime.now()
    year = now.strftime('%Y')
    month = now.strftime('%m')
    day = now.strftime('%d')
    hour = now.strftime('%H')
    minute = now.strftime('%M')

    params = {
        'username' : args.login,
        'auth_method' : 'challenge',
        'auth_challenge' : chal,
        'auth_response' : response,
        'subject' : stru[0]['header'],
        'event' : stru[0]['content'].encode('utf8'),
        'year': year,
        'mon': month,
        'day': day,
        'hour': hour,
        'min': minute,
    }

    if args.community == '':
        params['security'] = 'private'
    else:
        params['usejournal'] = args.community

    journal = args.community if args.community else args.login

    try:
        open('debug.zalupa2','w').write(json.dumps(params))
        post = lj.postevent(params)
        ditemid = post['ditemid']
        print post

        for id, x in enumerate(stru[1:], start=1):
            chal, response = get_chal(lj, passwd)
            params = {
                'username' : args.login,
                'auth_method' : 'challenge',
                'auth_challenge' : chal,
                'auth_response' : response,
                'journal' : journal,
                'ditemid' : ditemid,
                'parenttalkid' : 0,
                'body' : x['content'].encode('utf8'),
                'subject' : x['header']
                }
            print lj.addcomment(params)
    except:
        sys.stderr.write('Error issued by LJ API: {}'.format(
            traceback.format_exc()))
        sys.exit(1)

def lj_post_getdata():
    root = Tk()
    
    loginbox = Entry(root)
    pwdbox = Entry(root, show = '*')
    communitybox = Entry(root)
    
    def onpwdentry(evt):
        root.login = loginbox.get()
        root.password = pwdbox.get()
        root.community = communitybox.get()
        root.quit()
        root.destroy()
    def onokclick():
        root.login = loginbox.get()
        root.password = pwdbox.get()
        root.community = communitybox.get()
        root.quit()
        root.destroy()
    
    Label(root, text='Login').pack(side = 'top')
    loginbox.pack(side = 'top')
    Label(root, text = 'Password').pack(side = 'top')
    pwdbox.pack(side = 'top')
    Label(root, text='Community (may be blank)').pack(side = 'top')
    communitybox.pack(side = 'top')

    pwdbox.bind('<Return>', onpwdentry)
    loginbox.bind('<Return>', onpwdentry)
    communitybox.bind('<Return>', onpwdentry)

    Button(root, command=onokclick, text = 'OK').pack(side = 'top')

    root.mainloop()
    return root.login, root.password, root.community

def tex_format_question(q):
    yapper = texyapper
    if 'setcounter' in q:
        gui_compose.counter = int(q['setcounter'])
    res = ('\n\n\\begin{{samepage}}\n'
    '\\textbf{{Вопрос {}.}} {}'.format(gui_compose.counter 
        if not 'number' in q else q['number'], yapper
        (q['question'])))
    if not 'number' in q:
        gui_compose.counter += 1
    res += '\n\\textbf{{Ответ: }}{}'.format(yapper
        (q['answer']))
    if 'zachet' in q:
        res += '\n\\textbf{{Зачёт: }}{}'.format(yapper
        (q['zachet']))
    if 'nezachet' in q:
        res += '\n\\textbf{{Незачёт: }}{}'.format(yapper
        (q['nezachet']))
    if 'comment' in q:
        res += '\n\\textbf{{Комментарий: }}{}'.format(yapper
        (q['comment']))
    if 'source' in q:
        res += '\n\\textbf{{Источник{}: }}{}'.format(
        'и' if isinstance(q['source'], list) else '',
        yapper(q['source']))
    if 'author' in q:
        res += '\n\\textbf{{Автор: }}{}'.format(yapper
        (q['author']))
    res += '\n\\end{samepage}\\vspace{0.8em}\n'
    return res

def texrepl(zz):
    zz = re.sub(r"{",r"\{",zz) 
    zz = re.sub(r"}",r"\}",zz)
    zz = re.sub("_",r"\_",zz) 
    zz = re.sub(r"\^",r"{\\textasciicircum}",zz) 
    zz = re.sub(r"\~",r"{\\textasciitilde}",zz) 
    zz = re.sub(r"%",r"\%",zz) 
    zz = re.sub(r"\$",r"\$",zz) 
    zz = re.sub(r"#",r"\#",zz) 
    zz = re.sub(r"&",r"\&",zz) 
    zz = re.sub(r"\\",r"\\",zz) 
    zz = re.sub(r'((\"(?=[ \.\,;\:\?!\)\]]))|("(?=\Z)))',u'»',zz)
    zz = re.sub(r'(((?<=[ \.\,;\:\?!\(\[)])")|((?<=\A)"))',u'«',zz)
    zz = re.sub('"',"''",zz)
    
    for match in sorted([x for x in re_scaps.finditer(zz)],
        key=lambda x: len(x.group(2)), reverse=True):
        zz = zz.replace(match.group(2),
            '\\tsc{'+match.group(2).lower()+'}')


    # while re_scaps.search(zz):
    #     zz = zz.replace(re_scaps.search(zz).group(2),
    #         '\\tsc{'+re_scaps.search(zz).group(2).lower()+'}')

    torepl = [x.group(0) for x in re.finditer(re_url, zz)]
    for s in range(len(torepl)):
        item = torepl[s]
        while item[-1] in typotools.PUNCTUATION:
            item = item[:-1]
        while (item[-1] in typotools.CLOSING_BRACKETS and
            typotools.find_matching_opening_bracket(item, -1) is None):
            item = item[:-1]
        while item[-1] in typotools.PUNCTUATION:
            item = item[:-1]
        torepl[s] = item
    torepl = sorted(set(torepl), key=len, reverse=True)
    hashurls = {}
    for s in torepl:
        hashurls[s] = hashlib.md5(
            s.encode('utf8')).hexdigest().decode('utf8')
    for s in sorted(hashurls, key=len, reverse=True):
        zz = zz.replace(s, hashurls[s])
    hashurls = {v: k for k, v in hashurls.items()}
    for s in sorted(hashurls):
        zz = zz.replace(s, '\\url{{{}}}'.format(
            hashurls[s]))

    # debug_print('URLS FOR REPLACING: ' +pprint.pformat(torepl).decode('unicode_escape'))
    # while len(torepl)>0:
    #     s = torepl[0]
    #     debug_print('STRING BEFORE REPLACEMENT: {}'.format(zz))
    #     zz = zz.replace(s, '\\url{'+s+'}')
    #     debug_print('STRING AFTER REPLACEMENT: {}'.format(zz))
    #     torepl.pop(0)

    zz = zz.replace(' — ', '{\\hair}—{\\hair}')
    
    while '`' in zz:
        if zz.index('`') + 1 >= len(zz):
            zz = zz.replace('`', '')
        else:
            if (zz.index('`')+2 < len(zz) 
                and re.search(r'\s', zz[zz.index('`')+2])):
                zz = zz[:zz.index('`')+2]+'\\'+zz[zz.index('`')+2:]
            if (zz.index('`')+1 < len(zz) 
                and re_lowercase.search(zz[zz.index('`')+1])):
                zz = (zz[:zz.index('`')+1]+'\\acc{'
                    +zz[zz.index('`')+1]+'}'+zz[zz.index('`')+2:])
            elif (zz.index('`')+1 < len(zz) 
                and re_uppercase.search(zz[zz.index('`')+1])):
                zz = (zz[:zz.index('`')+1]+'\\cacc{'
                    +zz[zz.index('`')+1]+'}'+zz[zz.index('`')+2:])
            zz = zz[:zz.index('`')]+zz[zz.index('`')+1:]

    return zz

def texformat(s):
    res = ''
    for run in parse_4s_elem(s):
        if run[0] == '':
            res += texrepl(run[1])
        if run[0] == 'em':
            res += '\\emph{'+texrepl(run[1])+'}'
        if run[0] == 'img':
            imgfile, w, h = parseimg(run[1], dimensions='ems')
            res += ('\\includegraphics'+
                '[width={}{}]'.format(
                    '10em' if w==-1 else '{}em'.format(w),
                    ', height={}em'.format(h) if h!=-1 else ''
                    )+
                '{'+imgfile+'}')
    return res

def texyapper(e):
    if isinstance(e, basestring):
        return tex_element_layout(e)
    elif isinstance(e, list):
        if not any(isinstance(x, list) for x in e):
            return tex_element_layout(e)
        else:
            return '\n'.join([tex_element_layout(x) for x in e])

def tex_element_layout(e):
    res = ''
    if isinstance(e, basestring):
        res = texformat(e)
        return res
    if isinstance(e, list):
        res = """
\\begin{{enumerate}}
{}
\\end{{enumerate}}
""".format('\n'.join(
    ['\\item {}'.format(tex_element_layout(x)) for x in e]))
    return res

def gui_compose(largs):
    
    global im
    global args
    global console_mode
    args = largs
    global __file__                         # to fix stupid
    __file__ = os.path.abspath(__file__)    # __file__ handling
    _file_ = os.path.basename(__file__)     # in python 2

    global debug
    global TARGETDIR
    global SOURCEDIR
    
    root = Tk()
    root.withdraw()

    sys.stderr = codecs.getwriter('utf8')(sys.stderr)

    if args.debug:
        debug = True
    
    argsdict = vars(args)
    debug_print(pprint.pformat(argsdict))

    if (args.filename
        and args.filetype):
        if args.filetype == 'lj':
            if args.login and args.password:
                console_mode = True
        else:
            console_mode = True

    if args.filename is None:
        print('Choose .4s file to load:')
        args.filename = tkFileDialog.askopenfilename(
            filetypes=[('chgksuite markup files','*.4s')])
    if not args.filename:
        print('No file specified.')
        sys.exit(0)

    TARGETDIR = os.path.dirname(os.path.abspath(args.filename))
    filename = os.path.basename(os.path.abspath(args.filename))
    # if (os.path.abspath(SOURCEDIR.lower()) 
    #     != os.path.abspath(TARGETDIR.lower())):
    #     shutil.copy(os.path.abspath(args.filename), SOURCEDIR)
    with make_temp_directory(dir=SOURCEDIR) as tmp_dir:
        for fn in ['template.docx', 'fix-unnumbered-sections.sty',
                    'cheader.tex']:
            shutil.copy(os.path.join(SOURCEDIR, fn), tmp_dir)
        process_file(filename, args, tmp_dir)
        os.chdir(SOURCEDIR)
        # pdb.set_trace()

def process_file(filename, args, srcdir):
    SOURCEDIR = srcdir
    os.chdir(SOURCEDIR)
    with codecs.open(os.path.join(TARGETDIR, filename), 
        'r', 'utf8') as input_file:
            input_text = input_file.read()

    input_text = input_text.replace('\r','')

    structure = parse_4s(input_text, randomize=args.randomize)

    if args.debug:
        with codecs.open(
            make_filename(filename, 'dbg'), 'w', 'utf8') as output_file:
            output_file.write(
                pprint.pformat(structure).decode('unicode_escape'))

    if args.filetype is None:
        print('Choose type of export:')
        args.filetype, spoil, args.noanswers = gui_get_filetype()
        if not args.filetype:
            print('Filetype not specified.')
            sys.exit(0)
        if spoil:
            args.nospoilers = False
        else:
            args.nospoilers = True
        print('Exporting to {}, spoilers are {}...\n'
            .format(args.filetype, 'off' if args.nospoilers else 'on'))

    if args.filetype == 'docx':
        
        outfilename = os.path.join(SOURCEDIR,
            make_filename(filename, 'docx'))
        print(os.path.join(SOURCEDIR, 'template.docx'))
        gui_compose.doc = Document(os.path.join(SOURCEDIR, 'template.docx'))
        qcount = 0
        debug_print(pprint.pformat(structure).decode('unicode_escape'))
        
        for element in structure:
            if element[0] == 'meta':
                p = gui_compose.doc.add_paragraph()
                docx_format(element[1], p, False)
                gui_compose.doc.add_paragraph()
            
            if element[0] in ['editor', 'date', 'heading', 'section']:
                gui_compose.doc.add_paragraph(element[1]).alignment = 1
                gui_compose.doc.add_paragraph()
            
            if element[0] == 'Question':
                q = element[1]
                p = gui_compose.doc.add_paragraph()
                if not 'number' in q:
                    qcount += 1
                if 'setcounter' in q:
                    qcount = int(q['setcounter'])
                p.add_run('Вопрос {}. '.format(qcount
                    if not 'number' in q else q['number'])).bold = True
                
                if 'handout' in q:
                    p = gui_compose.doc.add_paragraph()
                    p.add_run('[Раздаточный материал: ')
                    docx_format(q['handout'], p, WHITEN['handout'])
                    p = gui_compose.doc.add_paragraph()
                    p.add_run(']')
                if not args.noparagraph:
                    p = gui_compose.doc.add_paragraph()
                
                docx_format(q['question'], p, False)
                p = gui_compose.doc.add_paragraph()
                
                if not args.noanswers:
                    p.add_run('Ответ: ').bold = True
                    docx_format(q['answer'], p, True)
                    
                    for field in ['zachet', 'nezachet',
                                    'comment', 'source', 'author']:
                        if field in q:
                            p = gui_compose.doc.add_paragraph()
                            if (field == 'source' 
                                and isinstance(q[field], list)):
                                p.add_run('Источники: ').bold = True
                            else:
                                p.add_run(FIELDS[field]).bold = True
                            docx_format(q[field], p, WHITEN[field])
                
                gui_compose.doc.add_paragraph()

        gui_compose.doc.save(outfilename)
        print('Output: {}'.format(
            os.path.join(TARGETDIR, outfilename)))
        if (os.path.abspath(SOURCEDIR.lower()) 
        != os.path.abspath(TARGETDIR.lower())):
            shutil.copy(outfilename, TARGETDIR)

    if args.filetype == 'tex':

        outfilename = os.path.join(SOURCEDIR,
            make_filename(filename, 'tex'))

        gui_compose.counter = 1

        title = 'Title'
        author = 'Author'
        date = '1970-01-01'
        for element in structure:
            if element[0] == 'heading':
                title = element[1]
            if element[0] == 'editor':
                author = element[1]
            if element[0] == 'date':
                date = element[1]
        gui_compose.tex = """\\input{{cheader.tex}}
\\title{{{title}}}
\\date{{{date}}}
\\author{{{author}}}
\\begin{{document}}
\\maketitle
\\obeylines
\\parskip=0pt
""".format(date=date, author=author, title=title)

        for element in structure:
            if element[0] == 'meta':
                gui_compose.tex += '\n{}\n\\vspace{{0.8em}}\n'.format(
                    tex_element_layout(element[1]))
            if element[0] == 'Question':
                gui_compose.tex += tex_format_question(element[1])

        gui_compose.tex += '\\end{document}'

        with codecs.open(outfilename, 'w', 'utf8') as outfile:
            outfile.write(gui_compose.tex)
        subprocess.call(shlex.split(
            'xelatex -synctex=1 -interaction=nonstopmode "{}"'
            .format(outfilename)))
        print('Output: {}'.format(
            os.path.join(TARGETDIR, 
                os.path.splitext(outfilename)[0]+'.tex'
                +'\n'
                + os.path.join(TARGETDIR, 
                    os.path.splitext(outfilename)[0]+'.pdf'))))
        if (os.path.normpath(SOURCEDIR.lower()) 
            != os.path.normpath(TARGETDIR.lower())):
            shutil.copy(os.path.splitext(outfilename)[0]+'.pdf', TARGETDIR)

    if args.filetype == 'lj':

        if not args.login:
            args.login, passwd, args.community = lj_post_getdata()
            if not args.login:
                print('Login not specified.')
                sys.exit(0)
        elif not args.password:
            import getpass
            passwd = getpass.getpass()
        
        CLIENT_ID = '8da1bd97da30ac1'
        im = pyimgur.Imgur(CLIENT_ID)

        gui_compose.counter = 1
        final_structure = [{'header': '',
        'content':''}]

        i = 0

        heading = ''
        ljheading = ''
        yapper = htmlyapper
        while structure[i][0] != 'Question':
            if structure[i][0] == 'heading':
                final_structure[0]['content'] += ('<h1>{}</h1>'
                    .format(yapper(structure[i][1])))
                heading = yapper(structure[i][1])
            if structure[i][0] == 'ljheading':
                # final_structure[0]['header'] = structure[i][1]
                ljheading = yapper(structure[i][1])
            if structure[i][0] == 'date':
                final_structure[0]['content'] += ('\n<center>{}</center>'
                    .format(yapper(structure[i][1])))
            if structure[i][0] == 'editor':
                final_structure[0]['content'] += ('\n<center>{}</center>'
                    .format(yapper(structure[i][1])))
            if structure[i][0] == 'meta':
                final_structure[0]['content'] += ('\n{}'
                    .format(yapper(structure[i][1])))
            i += 1

        if ljheading != '':
            final_structure[0]['header'] = ljheading
        else:
            final_structure[0]['header'] = heading

        for element in structure[i:]:
            if element[0] == 'Question':
                final_structure.append({'header': 'Вопрос {}'
                    .format(element[1]['number'] if 'number' in
                        element[1] else gui_compose.counter),
                    'content': html_format_question(element[1])})
            if element[0] == 'meta':
                final_structure.append({'header': '',
                    'content': yapper(element[1])})

        if debug:
            with codecs.open('lj.debug', 'w', 'utf8') as f:
                f.write(pprint.pformat(final_structure)
                    .decode('unicode_escape'))

        lj_post(final_structure, passwd)

    if not console_mode:
        raw_input("Press Enter to continue...")

def main():
    print('This program was not designed to run standalone.')
    raw_input("Press Enter to continue...")

if __name__ == '__main__':
    main()