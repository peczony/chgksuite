#!usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
import sys
import argparse
import pprint
import urllib
import re
import os
import sys
import codecs
import json
import typotools
from typotools import remove_excessive_whitespace as rew
import traceback
import datetime
from chgk_parser import QUESTION_LABELS

debug = False
re_url = re.compile(r"""((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]"""
"""|[a-z0-9.\-]+[.‌​][a-z]{2,4}/)(?:[^\s()<>]+|(([^\s()<>]+|(([^\s()<>]+)))*))+"""
"""(?:(([^\s()<>]+|(‌​([^\s()<>]+)))*)|[^\s`!()[]{};:'".,<>?«»“”‘’]))""", re.DOTALL) 
re_perc = re.compile(r'(%[0-9a-fA-F]{2})+')
re_scaps = re.compile(r'\s([А-Я`Ё]{2,})[\s,!\.;:-]')
re_em = re.compile(r'_(.+?)_')
re_lowercase = re.compile(r'[а-яё]')
re_uppercase = re.compile(r'[А-ЯЁ]')

REQUIRED_LABELS = set(['question', 'answer'])

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
    return os.path.splitext(s)[0]+'.'+ext

def parseimg(s):
    width = -1
    height = -1
    sp = s.split()
    if len(sp) == 1:
        return sp[0], -1, -1
    else:
        for spsp in sp[:-1]:
            spspsp = spsp.split('=')
            if spspsp[0] == 'w':
                width = spspsp[1]
            if spspsp[0] == 'h':
                height = spspsp[1]
        return sp[-1], width, height

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
        s = s.replace(gr,urllib.unquote(gr.encode('utf8')).decode('utf8'))
    
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


def parse_4s(s):
    mapping = {
        '#' : 'meta',
        '##' : 'section',
        '###' : 'heading',
        '#EDITOR': 'editor',
        '#DATE': 'date',
        '?': 'question',
        '!': 'answer',
        '=': 'zachet',
        '!=': 'nezachet',
        '^': 'source',
        '/': 'comment',
        '@': 'author',
        '>': 'handout',
    }

    structure = []
    
    for line in s.split('\n'):
        if rew(line) == '':
            structure.append(['', ''])
        else:
            if line.split()[0] in mapping:
                structure.append([mapping[line.split()[0]], 
                    rew(line[
                        len(line.split()[0]):])])
            else:
                if len(structure) > 1:
                    structure[len(structure)-1][1] += '\n' + line

    final_structure = []
    current_question = {}

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
                final_structure.append(['Question', current_question])
            
            current_question = {}

        else:
            final_structure.append([element[0], element[1]])
    
    if current_question != {}:
        assert all(True for label in REQUIRED_LABELS 
                if label in current_question)
        final_structure.append(['Question', current_question])

    return final_structure




def main():
    
    global debug

    sys.stderr = codecs.getwriter('utf8')(sys.stderr)

    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('filetype', nargs='?', default='docx')
    parser.add_argument('--debug', '-d', action='store_true')
    parser.add_argument('--nospoilers', '-n', action='store_true')
    parser.add_argument('--login', '-l')
    parser.add_argument('--community', '-c')
    args = parser.parse_args()

    if args.debug:
        debug = True

    with codecs.open(args.filename, 'r', 'utf8') as input_file:
            input_text = input_file.read()

    input_text = input_text.replace('\r','')

    structure = parse_4s(input_text)

    if args.debug:
        with codecs.open(
            make_filename(args.filename, 'dbg'), 'w', 'utf8') as output_file:
            output_file.write(
                pprint.pformat(structure).decode('unicode_escape'))

    if args.filetype == 'docx':
        import docx
        from docx import Document
        from parse import parse
        from docx.shared import Inches
        
        def docx_format(el, para, whiten):
            if isinstance(el, list):
                
                if len(el) > 1 and isinstance(el[1], list):
                    docx_format(el[0], para, whiten)
                    licount = 0
                    for li in el[1]:
                        licount += 1
                        
                        p = main.doc.add_paragraph('{}. '
                            .format(licount))
                        docx_format(li, p, whiten)
                else:
                    licount = 0
                    for li in el:
                        licount += 1
                        
                        p = main.doc.add_paragraph('{}. '
                            .format(licount))
                        docx_format(li, p, whiten)

            if isinstance(el, basestring):
                debug_print('parsing element {}:'
                    .format(pprint.pformat(el).decode('unicode_escape')))
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
                            para = main.doc.add_paragraph()
                    
                    elif run[0] == 'em':
                        r = para.add_run(run[1])
                        r.italic = True
                        if whiten and not args.nospoilers:
                            r.style = 'Whitened'
                        if images_exist:
                            para = main.doc.add_paragraph()

                    elif run[0] == 'sc':
                        r = para.add_run(run[1])
                        r.small_caps = True
                        if whiten and not args.nospoilers:
                            r.style = 'Whitened'
                        if images_exist:
                            para = main.doc.add_paragraph()
                    
                    elif run[0] == 'img':
                        width = -1
                        height = -1
                        sp = run[1].split()
                        if len(sp) == 1:
                            try:
                                main.doc.add_picture(run[1], width=Inches(4))
                            except:
                                sys.stderr.write(traceback.format_exc())
                        else:
                            for spsp in sp[:-1]:
                                spspsp = spsp.split('=')
                                if spspsp[0] == 'w':
                                    width = spspsp[1]
                                if spspsp[0] == 'h':
                                    height = spspsp[1]
                            
                            try:
                                if width == -1 and height == -1:
                                    main.doc.add_picture(sp[-1], width=Inches(4))
                                elif width != -1 and height == -1:
                                    main.doc.add_picture(sp[-1], width=width)
                                elif width == -1 and height != -1:
                                    main.doc.add_picture(sp[-1], height=height)
                                elif width != -1 and height != -1:
                                    main.doc.add_picture(sp[-1], width=width, 
                                        height=height)
                            except:
                                sys.stderr.write(traceback.format_exc())
                        
                        para = main.doc.add_paragraph()


        outfilename = make_filename(args.filename, 'docx')
        main.doc = Document('template.docx')
        qcount = 0
        debug_print(pprint.pformat(structure).decode('unicode_escape'))
        
        for element in structure:
            if element[0] == 'meta':
                p = main.doc.add_paragraph()
                p.add_run(element[1])
            
            if element[0] in ['editor', 'date', 'heading', 'section']:
                main.doc.add_paragraph(element[1]).alignment = 1
                main.doc.add_paragraph()
            
            if element[0] == 'Question':
                q = element[1]
                p = main.doc.add_paragraph()
                if not 'number' in q:
                    qcount += 1
                p.add_run('Вопрос {}. '.format(qcount
                    if not 'number' in q else q['number'])).bold = True
                
                if 'handout' in q:
                    p = main.doc.add_paragraph()
                    p.add_run('[Раздаточный материал: ')
                    docx_format(q['handout'], p, WHITEN['handout'])
                    p = main.doc.add_paragraph()
                    p.add_run(']')
                p = main.doc.add_paragraph()
                
                docx_format(q['question'], p, False)
                p = main.doc.add_paragraph()
                
                p.add_run('Ответ: ').bold = True
                docx_format(q['answer'], p, True)
                
                for field in ['zachet', 'nezachet',
                                'comment', 'source', 'author']:
                    if field in q:
                        p = main.doc.add_paragraph()
                        p.add_run(FIELDS[field]).bold = True
                        docx_format(q[field], p, WHITEN[field])
                
                main.doc.add_paragraph()

        main.doc.save(outfilename)

    if args.filetype == 'tex':

        outfilename = make_filename(args.filename, 'tex')

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
            
            while re_scaps.search(zz):
                zz = zz.replace(re_scaps.search(zz).group(1),
                    '\\tsc{'+re_scaps.search(zz).group(1).lower()+'}')
            
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
                    imgfile, w, h = parseimg(run[1])
                    res += ('\\includegraphics'+
                        '[width={}{}]'.format(
                            '10em' if w==-1 else w,
                            ', height={}'.format(h) if h!=-1 else ''
                            )+
                        '{'+texrepl(run[1])+'}')
            return res

        def yapper(e):
            if isinstance(e, basestring):
                return tex_element_layout(e)
            elif isinstance(e, list):
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

        main.counter = 1

        def tex_format_question(q):
            res = ('\n\n\\begin{{samepage}}\n'
            '\\textbf{{Вопрос {}.}} {}'.format(main.counter 
                if not 'number' in q else q['number'], yapper
                (q['question'])))
            if not 'number' in q:
                main.counter += 1
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
        main.tex = """\\input{{cheader.tex}}
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
                debug_print('chlen')
                main.tex += '\n{}\n'.format(tex_element_layout
                    (element[1]))
            if element[0] == 'Question':
                debug_print('anus')
                main.tex += tex_format_question(element[1])

        main.tex += '\\end{document}'

        with codecs.open(outfilename, 'w', 'utf8') as outfile:
            outfile.write(main.tex)

    if args.filetype == 'lj':
        if not args.login:
            sys.stderr.write('You must specify login with -l'
                ' to export to lj\n')
            sys.exit()
        from xmlrpclib import ServerProxy as s
        import getpass
        import urllib
        import hashlib

        def lj_post(stru):
            def md5(s):
                return hashlib.md5(s).hexdigest()

            def get_chal():
                chal = lj.getchallenge()['challenge']
                response = md5(chal + md5(passwd))
                return (chal,response)
             
            lj = s('http://www.livejournal.com/interface/xmlrpc').LJ.XMLRPC
             
            passwd = getpass.getpass()

            chal, response = get_chal()

            now = datetime.datetime.now()
            year = now.strftime('%Y')
            month = now.strftime('%m')
            day = now.strftime('%d')
            hour = now.strftime('%H')
            minute = now.strftime('%M')


            params = {
                'username' : 'pecheny',
                'auth_method' : 'challenge',
                'auth_challenge' : chal,
                'auth_response' : response,
                'subject' : 'Test post',
                'event' : stru[0].encode('utf8'),
                'security': 'private',

                'year': year,
                'mon': month,
                'day': day,
                'hour': hour,
                'min': minute,
            }

            if args.community == '':
                params['security'] = 'private'

            journal = args.community if args.community else args.login

            try:
                post = lj.postevent(params)
                ditemid = post['ditemid']
                print post

                for x in stru[1:]:
                    chal, response = get_chal()
                    params = {
                        'username' : args.login,
                        'auth_method' : 'challenge',
                        'auth_challenge' : chal,
                        'auth_response' : response,
                        'journal' : journal,
                        'ditemid' : ditemid,
                        'parenttalkid' : 0,
                        'body' : x.encode('utf8'),
                        'subject' : ''
                        }
                    print lj.addcomment(params)
            except:
                sys.stderr.write('Error issued by LJ API: {}'.format(
                    traceback.format_exc()))
                sys.exit()

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
                    res += ('<img '+
                        'width={}{}'.format(
                            '10em' if w==-1 else w,
                            ' height={}'.format(h) if h!=-1 else ''
                            )+
                        ' src="'+run[1]+'" />')
            return res

        def yapper(e):
            if isinstance(e, basestring):
                return html_element_layout(e)
            elif isinstance(e, list):
                return '\n'.join([html_element_layout(x) for x in e])

        def html_element_layout(e):
            res = ''
            if isinstance(e, basestring):
                res = htmlformat(e)
                return res
            if isinstance(e, list):
                res = """
<ol>
{}
</ol>
""".format('\n'.join(
    ['<li>{}</li>'.format(html_element_layout(x)) for x in e]))
                return res

        main.counter = 1

        def html_format_question(q):
            res = (
            '<strong>Вопрос {}.</strong> {}'.format(main.counter 
                if not 'number' in q else q['number'], yapper
                (q['question'])))
            if not 'number' in q:
                main.counter += 1
            res += '\n<strong>Ответ: </strong>{}{}{}'.format(
                '' if args.nospoilers else '<lj-spoiler>',
                yapper(q['answer']),
                '' if args.nospoilers else '</lj-spoiler>')
            if 'zachet' in q:
                res += '\n<strong>Зачёт: </strong>{}{}{}'.format(
                '' if args.nospoilers else '<lj-spoiler>',
                yapper(q['zachet']),
                '' if args.nospoilers else '</lj-spoiler>')
            if 'nezachet' in q:
                res += '\n<strong>Незачёт: </strong>{}{}{}'.format(
                '' if args.nospoilers else '<lj-spoiler>',
                yapper(q['nezachet']),
                '' if args.nospoilers else '</lj-spoiler>')
            if 'source' in q:
                res += '\n<strong>Источник{}: </strong>{}{}{}'.format(
                'и' if isinstance(q['source'], list) else '',
                '' if args.nospoilers else '<lj-spoiler>',
                yapper(q['source']),
                '' if args.nospoilers else '</lj-spoiler>')
            if 'comment' in q:
                res += '\n<strong>Комментарий: </strong>{}{}{}'.format(
                '' if args.nospoilers else '<lj-spoiler>',
                yapper(q['comment']),
                '' if args.nospoilers else '</lj-spoiler>')
            if 'author' in q:
                res += '\n<strong>Автор{}: </strong>{}'.format(
                'ы' if isinstance(q['author'], list) else '',
                yapper(q['author']))
            return res

        final_structure = ['']

        i = 0
        header = []
        while structure[i][0] != 'Question':
            if structure[i][0] == 'heading':
                final_structure[0] += ('<h1>{}</h1>'
                    .format(yapper(structure[i][1])))
            if structure[i][0] == 'date':
                final_structure[0] += ('\n<center>{}</center>'
                    .format(yapper(structure[i][1])))
            if structure[i][0] == 'editor':
                final_structure[0] += ('\n<center>{}</center>'
                    .format(yapper(structure[i][1])))
            if structure[i][0] == 'meta':
                final_structure[0] += ('\n{}'
                    .format(yapper(structure[i][1])))
            i += 1

        for element in [x for x in structure if x[0] == 'Question']:
            final_structure.append(html_format_question(x[1]))

        lj_post(final_structure)









if __name__ == '__main__':
    main()