import codecs
import random
import re
from collections import Counter

from chgksuite.common import QUESTION_LABELS, check_question, init_logger, log_wrap
from chgksuite.typotools import remove_excessive_whitespace as rew

REQUIRED_LABELS = set(["question", "answer"])
OVERRIDE_PREFIX = "!!"


def find_heading(structure):
    h_id = -1
    for e, x in enumerate(structure):
        if x[0] == "ljheading":
            return (e, x)
        elif x[0] == "heading":
            h_id = e
    if h_id >= 0:
        return (h_id, structure[h_id])
    return None


def find_tour(structure):
    for e, x in enumerate(structure):
        if x[0] == "section":
            return (e, x)
    return None


def check_if_zero(Question):
    number = Question.get("number")
    if number is None:
        return False
    if isinstance(number, int) and number == 0:
        return True
    if isinstance(number, str) and number.startswith(("0", "Размин")):
        return True
    return False


def process_list(element):
    if "-" not in element[1]:
        return
    sp = element[1].split("\n")
    sp = [rew(x) for x in sp]
    list_markers = [i for i in range(len(sp)) if sp[i].startswith("-")]
    if not list_markers:
        return
    preamble = "\n".join(sp[: list_markers[0]])
    inner_list = []
    for num, index in enumerate(list_markers):
        if (num + 1) == len(list_markers):
            inner_list.append(rew("\n".join(sp[index:])[1:]))
        else:
            inner_list.append(rew("\n".join(sp[index : list_markers[num + 1]])[1:]))
    if len(inner_list) == 1:
        element[1] = rew(re.sub("(^|\n)- +", "\\1", element[1]))
    elif preamble:
        element[1] = [preamble, inner_list]
    else:
        element[1] = inner_list


RE_COUNTER = re.compile("4SCOUNTER([0-9a-zA-Z_]*)")


def replace_counters(string_):
    dd = Counter()
    match = RE_COUNTER.search(string_)
    while match:
        span = match.span()
        counter_id = match.group(1)
        dd[counter_id] += 1
        string_ = string_[: span[0]] + str(dd[counter_id]) + string_[span[1] :]
        match = RE_COUNTER.search(string_)
    return string_


def parse_4s(s, randomize=False, debug=False, logger=None):
    logger = logger or init_logger("composer")
    mapping = {
        "#": "meta",
        "##": "section",
        "###": "heading",
        "###LJ": "ljheading",
        "#EDITOR": "editor",
        "#DATE": "date",
        "?": "question",
        "№": "number",
        "№№": "setcounter",
        "!": "answer",
        "=": "zachet",
        "!=": "nezachet",
        "^": "source",
        "/": "comment",
        "@": "author",
        ">": "handout",
    }

    structure = []

    if s[0] == "\ufeff" and len(s) > 1:
        s = s[1:]

    with codecs.open("raw.debug", "w", "utf8") as debugf:
        debugf.write(log_wrap(s.split("\n")))

    s = replace_counters(s)

    for line in s.split("\n"):
        if rew(line) == "":
            structure.append(["", ""])
        else:
            if line.split()[0] in mapping:
                structure.append(
                    [mapping[line.split()[0]], rew(line[len(line.split()[0]) :])]
                )
            else:
                if len(structure) >= 1:
                    structure[len(structure) - 1][1] += "\n" + line

    final_structure = []
    current_question = {}
    counter = 1

    if debug:
        with codecs.open("debug1st.debug", "w", "utf8") as debugf:
            debugf.write(log_wrap(structure))

    for element in structure:
        # find list in element

        process_list(element)

        if element[0] in QUESTION_LABELS:
            if element[0] in current_question:
                if isinstance(current_question[element[0]], str) and isinstance(
                    element[1], str
                ):
                    current_question[element[0]] += "\n" + element[1]

                elif isinstance(current_question[element[0]], list) and isinstance(
                    element[1], str
                ):
                    current_question[element[0]][0] += "\n" + element[1]

                elif isinstance(current_question[element[0]], str) and isinstance(
                    element[1], list
                ):
                    current_question[element[0]] = [
                        element[1][0] + "\n" + current_question[element[0]],
                        element[1][1],
                    ]

                elif isinstance(current_question[element[0]], list) and isinstance(
                    element[1], list
                ):
                    current_question[element[0]][0] += "\n" + element[1][0]
                    current_question[element[0]][1] += element[1][1]
            else:
                current_question[element[0]] = element[1]

        elif element[0] == "":
            if current_question != {} and set(current_question.keys()) != {
                "setcounter"
            }:
                try:
                    assert all(
                        (True if label in current_question else False)
                        for label in REQUIRED_LABELS
                    )
                except AssertionError:
                    logger.error(
                        "Question {} misses "
                        "some of the required fields "
                        "and will therefore "
                        "be omitted.".format(log_wrap(current_question))
                    )
                    continue
                if "setcounter" in current_question:
                    counter = int(current_question["setcounter"])
                if "number" not in current_question:
                    current_question["number"] = counter
                    counter += 1
                final_structure.append(["Question", current_question])

                current_question = {}

        else:
            final_structure.append([element[0], element[1]])

    if current_question != {}:
        try:
            assert all(
                (True if label in current_question else False)
                for label in REQUIRED_LABELS
            )
            if "setcounter" in current_question:
                counter = int(current_question["setcounter"])
            if "number" not in current_question:
                current_question["number"] = counter
                counter += 1
            final_structure.append(["Question", current_question])
        except AssertionError:
            logger.error(
                "Question {} misses "
                "some of the required fields and will therefore "
                "be omitted.".format(log_wrap(current_question))
            )

    if randomize:
        random.shuffle(final_structure, lambda: 0.3)
        i = 1
        for element in final_structure:
            if element[0] == "Question":
                element[1]["number"] = i
                i += 1

    if debug:
        with codecs.open("debug.debug", "w", "utf8") as debugf:
            debugf.write(log_wrap(final_structure))

    for element in final_structure:
        if element[0] == "Question":
            check_question(element[1], logger=logger)
            for field in [
                "handout",
                "question",
                "answer",
                "zachet",
                "nezachet",
                "comment",
                "source",
                "author",
            ]:
                val = element[1].get(field)
                if val is None:
                    continue
                is_list = False
                if isinstance(val, list):
                    is_list = True
                    val = val[0]
                sp = val.split(" ", 1)
                if len(sp) == 1:
                    continue
                sp1, sp2 = sp
                if sp1.startswith(OVERRIDE_PREFIX):
                    if "overrides" not in element[1]:
                        element[1]["overrides"] = {}
                    element[1]["overrides"][field] = sp1[
                        len(OVERRIDE_PREFIX) :
                    ].replace("~", " ")
                    if is_list:
                        element[1][field][0] = sp2
                    else:
                        element[1][field] = sp2

    return final_structure
