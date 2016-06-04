#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import sys
import os
import re
import json
import codecs
import requests
import pdb
import webbrowser
from collections import defaultdict
from chgk_composer import on_close
try:
    from Tkinter import Tk, Frame, IntVar, Button, Checkbutton
    import tkFileDialog as filedialog
except ImportError:
    from tkinter import Tk, Frame, IntVar, Button, Checkbutton
    from tkinter import filedialog
try:
    basestring
except NameError:
    basestring = str
try:
    input = raw_input
except NameError:
    pass


API = 'https://trello.com/1'


def gui_file_or_directory(args):

    ch_author = IntVar()
    try:
        ch_author.set(int(args.author))
    except TypeError:
        ch_author.set(0)

    def filereturn():
        root.ret['action'] = 'files'
        root.quit()
        root.destroy()

    def directoryreturn():
        root.ret['action'] = 'directory'
        root.quit()
        root.destroy()

    def toggle_au():
        if ch_author.get() == 0:
            ch_author.set(1)
        else:
            ch_author.set(0)
        root.ret['author'] = bool(ch_author.get())

    root = Tk()
    root.title('upload file(s) or directory')
    root.eval('tk::PlaceWindow . center')
    root.ret = {'action': '', 'author': False}
    root.grexit = lambda: on_close(root)
    root.protocol("WM_DELETE_WINDOW", root.grexit)
    root.attributes("-topmost", True)
    frame = Frame(root)
    frame.pack()
    bottomframe = Frame(root)
    bottomframe.pack(side='bottom')

    Button(frame, command=filereturn, text='Upload file(s)').pack(
        side='left',
        padx=20, pady=20,
        ipadx=20, ipady=20,)
    Button(frame, command=directoryreturn, text='Upload directory').pack(
        side='left',
        padx=20, pady=20,
        ipadx=20, ipady=20,)
    au = Checkbutton(bottomframe, text='Display authors in cards’ captions',
                     variable=ch_author, command=toggle_au)

    if ch_author.get() == 1:
        au.select()
    root.ret['author'] = bool(ch_author.get())
    root.mainloop()
    return root.ret


def upload_file(filepath, trello):
    req = requests.get("{}/boards/{}/lists".format(API, trello['board_id']),
                       data={'token': trello['params']['token'],
                             'key': trello['params']['key']})
    if req.status_code != 200:
        print('Error: {}'.format(req.text))
        sys.exit(1)

    lists = json.loads(req.content.decode('utf8'))
    lid = lists[0]['id']
    content = ''
    with codecs.open(filepath, 'r', 'utf8') as f:
        content = f.read()
    cards = re.split(r'(\r?\n){2,}', content)
    cards = [x for x in cards if x != '' and x != '\n' and x != '\r\n']
    for card in cards:
        caption = 'вопрос'
        if re.search('\n! (.+?)\r?\n', card):
            caption = re.search('\n! (.+?)\.?\r?\n', card).group(1)
            if trello['author'] and re.search('\n@ (.+?)\.?\r?\n', card):
                caption += ' {}'.format(
                    re.search('\n@ (.+?)\r?\n', card).group(1))

        req = requests.post(
            "{}/lists/{}/cards".format(API, lid),
            {
                'key': trello['params']['key'],
                'token': trello['params']['token'],
                'desc': card,
                'name': caption
            })
        if req.status_code == 200:
            print('Successfully sent {}'.format(caption))
        else:
            print('Error {}: {}'.format(req.status_code, req.content))


def gui_trello_upload(args):
    ld = '.'
    if os.path.isfile('lastdir'):
        with codecs.open('lastdir', 'r', 'utf8') as f:
            ld = f.read().rstrip()
        if not os.path.isdir(ld):
            ld = '.'

    if not args.trelloconfig:
        args.trelloconfig = filedialog.askopenfilename(
            filetypes=[('JSON files', '*.json')],
            initialdir=ld
        )

    trelloconfig = json.load(open(args.trelloconfig))
    ld = os.path.dirname(args.trelloconfig)
    with codecs.open('lastdir', 'w', 'utf8') as f:
        f.write(ld)

    if not args.filename:
        file_or_directory = gui_file_or_directory(args)
        args.author = file_or_directory['author']
        if file_or_directory['action'] == 'files':
            args.filename = filedialog.askopenfilenames(
                filetypes=[('chgksuite markup files', '*.4s')],
                initialdir=ld
            )
        elif file_or_directory['action'] == 'directory':
            args.filename = filedialog.askdirectory(
                initialdir=ld
            )

    trelloconfig['author'] = args.author

    if isinstance(args.filename, (list, tuple)):
        if len(args.filename) == 1 and os.path.isdir(args.filename[0]):
            for filename in os.listdir(args.filename[0]):
                if filename.endswith('.4s'):
                    filepath = os.path.join(args.filename[0], filename)
                    upload_file(filepath, trelloconfig)
        else:
            for filename in args.filename:
                upload_file(filename, trelloconfig)
    elif isinstance(args.filename, basestring):
        if os.path.isdir(args.filename):
            for filename in os.listdir(args.filename):
                if filename.endswith('.4s'):
                    filepath = os.path.join(args.filename, filename)
                    upload_file(filepath, trelloconfig)
        elif os.path.isfile(args.filename):
            upload_file(args.filename, trelloconfig)


def process_desc(s):
    return s.replace(r'\`', '`')


def getlabels(s):
    return {x['name'] for x in s['labels']}


def gui_trello_download(args):

    ld = '.'
    if os.path.isfile('lastdir'):
        with codecs.open('lastdir', 'r', 'utf8') as f:
            ld = f.read().rstrip()
        if not os.path.isdir(ld):
            ld = '.'

    if not args.trelloconfig:
        args.trelloconfig = filedialog.askopenfilename(
            filetypes=[('JSON files', '*.json')],
            initialdir=ld
        )

    trelloconfig = json.load(open(args.trelloconfig))
    ld = os.path.dirname(args.trelloconfig)
    with codecs.open('lastdir', 'w', 'utf8') as f:
        f.write(ld)
    os.chdir(os.path.dirname(args.trelloconfig))

    if args.si:
        from docx import Document

    board_id = trelloconfig['board_id']
    params = trelloconfig['params']

    req = requests.get("{}/boards/{}".format(API, board_id),
                       data=params)
    if req.status_code != 200:
        print('Error: {}'.format(req.text))
        if args.debug:
            pdb.set_trace()
        sys.exit(1)

    _lists = defaultdict(lambda: [])

    json_ = json.loads(req.content.decode('utf8'))
    _names = {}
    for list_ in json_['lists']:
        _names[list_['id']] = list_['name']
    for name in _names:
        _names[name] = _names[name].replace('/', '_')
    if args.si:
        _docs = defaultdict(lambda: Document('template.docx'))
    for card in json_['cards']:
        if args.si:
            p = _docs[_names[card['idList']]].add_paragraph()
            p.add_run(
                'Тема {}. '.format(
                    len(_lists[_names[card['idList']]]) + 1
                ) + card['name']).bold = True
            p = _docs[_names[card['idList']]].add_paragraph()
            p = _docs[_names[card['idList']]].add_paragraph()
            p.add_run(process_desc(card['desc']))
            p = _docs[_names[card['idList']]].add_paragraph()
            p = _docs[_names[card['idList']]].add_paragraph()
        _lists[_names[card['idList']]].append(
            ('Тема {}. '.format(
                len(_lists[_names[card['idList']]]) + 1
            ) + card['name'] + '\n\n' if args.si else '') +
            process_desc(card['desc'])
        )
        if args.labels:
            for label in getlabels(card):
                _lists[label].append(
                    (card['name'] if args.si else '') +
                    process_desc(card['desc']))
    if args.si:
        for doc in _docs:
            _docs[doc].save('{}.docx'.format(doc))

    for _list in _lists:
        filename = '{}.4s'.format(_list)
        print('outputting {}'.format(filename))
        with codecs.open(filename, 'w', 'utf8') as f:
            for item in _lists[_list]:
                f.write('\n' + item + '\n')


def gui_trello(args):
    if args.trellosubcommand == 'download':
        gui_trello_download(args)
    elif args.trellosubcommand == 'upload':
        gui_trello_upload(args)
    elif args.trellosubcommand == 'token':
        webbrowser.open('https://trello.com/1/connect'
                        '?key=1d4fe71dd193855686196e7768aa4b05'
                        '&name=Chgk&scope=read,write&response_type=token')


def main():
    print('This program was not designed to run standalone.')
    input("Press Enter to continue...")


if __name__ == "__main__":
    main()
