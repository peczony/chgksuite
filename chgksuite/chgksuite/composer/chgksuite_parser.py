import os
import random
import re
from collections import defaultdict

from chgksuite.common import (
    QUESTION_LABELS,
    check_question,
    get_chgksuite_dir,
    init_logger,
    log_wrap,
)
from chgksuite.typotools import remove_excessive_whitespace as rew

REQUIRED_LABELS = {"question", "answer"}
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
    return bool(isinstance(number, str) and number.startswith(("0", "Размин")))


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


RE_COUNTER = "4SCOUNTER(?P<counter_id>[0-9a-zA-Z_]*)"
RE_SET_COUNTER = (
    "set 4SCOUNTER(?P<counter_id_set>[0-9a-zA-Z_]*) = (?P<counter_value>[0-9+]+)"
)
RE_COUNTER_UNIFY = re.compile(f"({RE_COUNTER}|{RE_SET_COUNTER})")


def replace_counters(string_):
    dd = defaultdict(lambda: 1)
    match = RE_COUNTER_UNIFY.search(string_)
    while match:
        span = match.span()
        if re.search(RE_SET_COUNTER, match.group(0)):
            counter_id = match.group("counter_id_set")
            counter_value = int(match.group("counter_value"))
            dd[counter_id] = counter_value
            string_ = string_[: span[0]] + string_[span[1] :]
        else:
            span = match.span()
            counter_id = match.group("counter_id")
            string_ = string_[: span[0]] + str(dd[counter_id]) + string_[span[1] :]
            dd[counter_id] += 1
        match = RE_COUNTER_UNIFY.search(string_)
    return string_


def parse_4s(
    s, randomize=False, debug=False, logger=None, debug_dir=None, required_fields=None,
    game=None,
):
    logger = logger or init_logger("composer")
    if required_fields is None and game in ("si", "troika"):
        required_fields = {"question", "answer"}
    mapping = {
        "#": "meta",
        "##": "section",
        "###": "heading",
        "###LJ": "ljheading",
        "#B": "battle",
        "#R": "round",
        "#T": "theme",
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

    if debug:
        debug_dir = debug_dir or get_chgksuite_dir()
        debug_path = os.path.join(debug_dir, "raw.debug")
        with open(debug_path, "w", encoding="utf-8") as debugf:
            debugf.write(log_wrap(s.split("\n")))

    s = replace_counters(s)

    for line in s.split("\n"):
        line_parts = line.split()
        if rew(line) == "" or not line_parts:
            structure.append(["", ""])
        else:
            if line_parts[0] in mapping:
                structure.append(
                    [mapping[line_parts[0]], rew(line[len(line_parts[0]) :])]
                )
            else:
                if len(structure) >= 1:
                    structure[len(structure) - 1][1] += "\n" + line

    final_structure = []
    current_question = {}
    counter = 1

    if debug:
        with open("debug1st.debug", "w", encoding="utf-8") as debugf:
            debugf.write(log_wrap(structure))

    for element in structure:
        # find list in element

        process_list(element)

        if element[0] in QUESTION_LABELS:
            # Pass through standalone fields that aren't part of a question
            if not current_question and element[0] not in (
                "question",
                "answer",
                "number",
                "setcounter",
            ):
                final_structure.append([element[0], element[1]])
            elif element[0] in current_question:
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
                        (label in current_question)
                        for label in REQUIRED_LABELS
                    )
                except AssertionError:
                    logger.error(
                        f"Question {log_wrap(current_question)} misses "
                        "some of the required fields "
                        "and will therefore "
                        "be omitted."
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
            if element[0] == "theme":
                counter = 1 if game == "troika" else 10
            elif game in ("brain", "troika") and element[0] in ("battle", "section"):
                counter = 1
            final_structure.append([element[0], element[1]])

    if current_question != {}:
        try:
            assert all(
                (label in current_question)
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
                f"Question {log_wrap(current_question)} misses "
                "some of the required fields and will therefore "
                "be omitted."
            )

    # Number SI/Troika themes inline so every consumer can rely on the same numbering.
    # The theme counter resets on each battle and section boundary.
    theme_number = 0
    for element in final_structure:
        if element[0] in ("battle", "section"):
            theme_number = 0
        elif element[0] == "theme" and isinstance(element[1], str):
            theme_number += 1
            raw_name = element[1]
            m_theme_label = re.match(
                r"(?i)^тема\s+\d+(?:\s*\([^)]+\))?\.\s*(.+)", raw_name
            )
            if m_theme_label:
                name = m_theme_label.group(1).strip()
                label = raw_name
            else:
                name = raw_name
                label = f"Тема {theme_number}. {name}"
            element[1] = {
                "name": name,
                "number": theme_number,
                "label": label,
            }

    if randomize:
        random.shuffle(final_structure)
        i = 1
        for element in final_structure:
            if element[0] == "Question":
                element[1]["number"] = i
                i += 1

    if debug:
        with open("debug.debug", "w", encoding="utf-8") as debugf:
            debugf.write(log_wrap(final_structure))

    for element in final_structure:
        if element[0] == "Question":
            check_question(element[1], logger=logger, required_fields=required_fields)
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
