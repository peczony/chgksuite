#!/usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import sys
import os
import re
import codecs
import argparse
import requests
import json
import pdb
from collections import defaultdict

# To obtain a token, please copy & paste 
# to the address bar of your browser 
# the following link:
# https://trello.com/1/connect?key=1d4fe71dd193855686196e7768aa4b05&name=Chgk&scope=read,write&response_type=token
# Then copy & paste the obtained token 
# to the "token" field in the trello.json
#
# You're almost done. Now, when you are
# browsing your board, in the address bar
# you see a link like 
# https://trello.com/b/d1ISB5RC/-
# Copy and paste the `d1ISB5RC`-like part
# to the "board_id" field in the trello.json
#
# Now you can run the script.

def process_desc(s):
    return s.replace(r'\`','`')

def upload_file(filepath, lid, trello):
    content = ''
    with codecs.open(filepath, 'r', 'utf8') as f:
        content = f.read()
    cards = re.split(r'(\r?\n){2,}',content)
    cards = [x for x in cards if x != '' and x != '\n' and x != '\r\n']
    for card in cards:
        caption = 'вопрос'
        if re.search('\n! (.+?)\r?\n', card):
            caption = re.search('\n! (.+?)\r?\n', card).group(1)
        req = requests.post(
            "https://trello.com/1/lists/{}/cards".format(lid),
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--config', default='trello.json',
        help="Use this if you want to use a file named "
        "differently than the default trello.json")
    parser.add_argument('--debug', action='store_true',
        help=argparse.SUPPRESS)

    args = parser.parse_args()
    with open(args.config, 'r') as f:
        trello = json.loads(f.read())
    board_id = trello['board_id']
    params = trello['params']

    req = requests.get("https://trello.com/1/boards/{}/lists".format(board_id),
        data={'token': trello['params']['token'], 'key': trello['params']['key']})
    if req.status_code != 200:
        print('Error: {}'.format(req.text))
        if args.debug:
            pdb.set_trace()
        sys.exit(1)
    
    lists = json.loads(req.content)
    lid = lists[0]['id']

    if os.path.isfile(args.filename):
        upload_file(os.path.abspath(args.filename), lid, trello)
    elif os.path.isdir(args.filename):
        for filename in os.listdir(args.filename):
            if filename.endswith(b'.4s'):
                upload_file(os.path.join(args.filename, filename), 
                    lid, trello)

if __name__ == "__main__":
    main()