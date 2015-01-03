#!usr/bin/env python
#! -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import division
import sys
import codecs
import chgk_composer
import argparse
from collections import Counter

parser = argparse.ArgumentParser()
parser.add_argument('filename')
args = parser.parse_args()

authors = Counter()

with codecs.open(args.filename, 'r', 'utf-8') as f:
    structure = chgk_composer.parse_4s(f.read().replace('\r',''))

for element in structure:
    if element[0] == 'Question':
        if 'author' in element[1]:
            authors[element[1]['author'].replace('`','')] += 1

for au in authors.most_common():
    print('{}\t{}'.format(au[0],au[1]))


