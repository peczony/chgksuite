import functools
import logging
import re
import unicodedata
import urllib.parse

unquote = urllib.parse.unquote_to_bytes

logger = logging.getLogger(__name__)

WHITESPACE = {" ", " ", "\n"}
PUNCTUATION = {",", ".", ":", ";", "?", "!"}
OPENING_BRACKETS = ["[", "(", "{"]
CLOSING_BRACKETS = ["]", ")", "}"]
LOWERCASE_RUSSIAN = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
UPPERCASE_RUSSIAN = set("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
POTENTIAL_ACCENTS = set("АОУЫЭЯЕЮИ")
BAD_BEGINNINGS = {"Мак", "мак", "О'", "о’", "О’", "о'"}
NO_BREAK_SEQUENCES = [
    "а",
    "без",
    "в",
    "во",
    "где",
    "для",
    "же",
    "за",
    "и",
    "или",
    "из",
    "из-за",
    "к",
    "как",
    "на",
    "над",
    "не",
    "ни",
    "но",
    "о",
    "от",
    "по",
    "под",
    "при",
    "с",
    "со",
    "то",
    "у",
    "что",
    "перед",
]
NO_BREAK_SEQUENCES_LEFT = ["бы", "ли", "же", "—", "–"]
LETTERS_MAPPING = {"a": "а", "e": "е", "y": "у", "o": "о", "u": "и"}
for x in list(LETTERS_MAPPING.keys()):
    LETTERS_MAPPING[x.upper()] = LETTERS_MAPPING[x].upper()
CYRILLIC_CHARS = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
СYRILLIC_CHARS = set(CYRILLIC_CHARS + CYRILLIC_CHARS.upper())

re_bad_wsp_start = re.compile(r"^[{}]+".format("".join(WHITESPACE)))
re_bad_wsp_end = re.compile(r"[{}]+$".format("".join(WHITESPACE)))
re_url = re.compile(
    r"""((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]"""
    """|[a-z0-9.\\-]+[.‌\u200b][a-z]{2,4}/)(?:[^\\s()<>]+|(([^\\s()<>]+|(([^\\s()<>]+)))*))+"""
    """(?:(([^\\s()<>]+|(‌\u200b([^\\s()<>]+)))*)|[^\\s`!()[]{};:'".,<>?«»“”‘’]))""",
    re.DOTALL,
)
re_percent = re.compile(r"(%[0-9a-fA-F]{2})+")
re_nbh = re.compile(
    "(^|[^а-яё])(?P<word>[а-яё]{0,3}\\-[а-яё]{0,3})([^а-яё]|$)", flags=re.IGNORECASE
)
re_lowercase = re.compile(r"[а-яё]")
re_uppercase = re.compile(r"[А-ЯЁ]")


def _iter_http_url_spans(s):
    i = 0
    while i < len(s):
        if s.startswith(("http://", "https://"), i):
            j = i + 1
            bracket_level = 0
            while j < len(s) and not (
                s[j].isspace() or s[j] == ")" and bracket_level == 0
            ):
                if s[j] == "(":
                    bracket_level += 1
                elif s[j] == ")" and bracket_level > 0:
                    bracket_level -= 1
                j += 1
            end = j - 1 if s[j - 1] in (",", ".", ";") else j
            yield i, end
            i = j
        else:
            i += 1


def iter_url_spans(s):
    spans = list(_iter_http_url_spans(s))
    spans.extend(match.span() for match in re_url.finditer(s))
    spans = sorted(span for span in spans if span[0] < span[1])
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def escape_underscores_except_urls(s, skip_escaped=False):
    def escape_segment(segment):
        if skip_escaped:
            return re.sub(r"(?<!\\)_", r"\\_", segment)
        return segment.replace("_", r"\_")

    if "_" not in s:
        return s
    parts = []
    last = 0
    for start, end in iter_url_spans(s):
        parts.append(escape_segment(s[last:start]))
        parts.append(s[start:end])
        last = end
    parts.append(escape_segment(s[last:]))
    return "".join(parts)


def strings_iterator(str_):
    result = []
    if isinstance(str_, str):
        return [str_]
    elif isinstance(str_, list):
        for el in str_:
            result.extend(strings_iterator(el))
    elif isinstance(str_, dict):
        for v in str_.values():
            result.extend(strings_iterator(v))
    return result


@functools.cache
def uni_normalize(k):
    return unicodedata.normalize("NFD", k)


def cyr_lat_check_char(i, char, word):
    if char.lower() in CYRILLIC_CHARS:
        return
    if not (
        (i == 0 or word[i - 1].lower() in CYRILLIC_CHARS or not word[i - 1].isalpha())
        and (
            i == len(word) - 1
            or word[i + 1].lower() in CYRILLIC_CHARS
            or not word[i + 1].isalpha()
        )
    ):
        return
    norm = uni_normalize(char)
    if norm != char and norm[0] in LETTERS_MAPPING and norm[1] in ACCENTS_TO_FIX:
        return LETTERS_MAPPING[norm[0]] + "\u0301" + norm[2:]
    return


ACCENTS_TO_FIX = {"\u0300", "\u0341", "\u0301"}


def cyr_lat_check_word(word):
    if len(word) == 1:
        return
    replacements = {}
    for i, char in enumerate(word):
        check_result = cyr_lat_check_char(i, char, word)
        if check_result:
            replacements[char] = check_result
        elif (
            char.lower() in CYRILLIC_CHARS
            and i < len(word) - 1
            and word[i + 1] in ACCENTS_TO_FIX
        ):
            replacements[char + word[i + 1]] = char + "\u0301"
    if replacements:
        for k, v in replacements.items():
            word = word.replace(k, v)
        return word
    return


def fix_accents_func(str_, mode="on"):
    if mode in ("on", "smart"):
        str_ = detect_accent(str_)
    replacements = {}
    for word in str_.split():
        if check := cyr_lat_check_word(word):
            replacements[word] = check
    for rep, value in replacements.items():
        str_ = str_.replace(rep, value)
    return str_


def remove_excessive_whitespace(s):
    s = re_bad_wsp_start.sub("", s)
    s = re_bad_wsp_end.sub("", s)
    s = re.sub(r"\s+\n\s+", "\n", s)
    return s


class QuoteFixer:
    def __init__(self, s):
        self.s = s
        self.new_s = list(s)
        self.level = 0
        self.last_opening_quote = {}
        self.quote_chars = {}

    def is_space(self, char):
        return char in (" ", "\u00a0")

    def prev(self, c, i):
        if i < 0:
            raise IndexError("not allowed")
        if i == 0:
            return None
        return c[i - 1]

    def next(self, c, i):
        if i >= len(c):
            raise IndexError("not allowed")
        if i + 1 == len(c):
            return None
        return c[i + 1]

    def fix(self):
        c = self.new_s
        for i in range(len(c)):
            if c[i] in ("«", "„"):
                self.level += 1
                self.quote_chars[i] = ("opening", self.level, c[i], i)
                self.last_opening_quote[self.level] = c[i]
            elif c[i] in ("»", "”"):
                self.quote_chars[i] = ("closing", self.level, c[i], i)
                self.level -= 1
            elif c[i] == '"':
                if self.level == 0 or (
                    self.prev(c, i) is None
                    or (
                        self.is_space(self.prev(c, i))
                        and (
                            self.next(c, i) is not None
                            and not self.is_space(self.next(c, i))
                        )
                    )
                ):
                    self.level += 1
                    self.quote_chars[i] = ("opening", self.level, c[i], i)
                    self.last_opening_quote[self.level] = c[i]
                elif self.last_opening_quote.get(self.level) == '"':
                    self.quote_chars[i] = ("closing", self.level, c[i], i)
                    self.level -= 1
                else:
                    self.level += 1
                    self.quote_chars[i] = ("opening", self.level, c[i], i)
                    self.last_opening_quote[self.level] = c[i]
            elif c[i] == "“":
                if self.last_opening_quote.get(self.level) == "„":
                    self.quote_chars[i] = ("closing", self.level, c[i], i)
                    self.level -= 1
                else:
                    self.level += 1
                    self.quote_chars[i] = ("opening", self.level, c[i], i)
        if self.level != 0:
            return self.s
        for qc in self.quote_chars:
            tup = self.quote_chars[qc]
            if tup[0] == "opening":
                if tup[1] % 2:
                    self.new_s[qc] = "«"
                else:
                    self.new_s[qc] = "„"
            elif tup[0] == "closing":
                if tup[1] % 2:
                    self.new_s[qc] = "»"
                else:
                    self.new_s[qc] = "“"
            else:
                raise ValueError(f"unexpected quote kind {tup[0]}")
        return "".join(self.new_s)


def get_quotes_right(s_in):
    s = s_in

    if '"' in s or ("“" in s and "„" not in s):
        s = QuoteFixer(s).fix()

    s = re.sub(r"(\w)'", r"\1’", s, flags=re.UNICODE)
    s = re.sub(r"'(\w)", r"‘\1", s, flags=re.UNICODE)

    return s


def get_dashes_right(s):
    s = re.sub(r"(?<=\s)-+(?=\s)", "—", s)
    s = s.replace(" – ", " — ")
    return s


def _replace_no_break_segment(s, spaces=True, hyphens=True):
    if spaces:
        for sp in NO_BREAK_SEQUENCES + [x.title() for x in NO_BREAK_SEQUENCES]:
            r_from = f"(^|[ \u00a0]){sp} "
            r_to = f"\\g<1>{sp}\u00a0"
            s = re.sub(r_from, r_to, s)
        for sp in NO_BREAK_SEQUENCES_LEFT + [
            x.title() for x in NO_BREAK_SEQUENCES_LEFT
        ]:
            r_from = f" {sp}([ \u00a0]|$)"
            r_to = f"\u00a0{sp}\\g<1>"
            s = re.sub(r_from, r_to, s)
    if hyphens:
        srch = re_nbh.search(s)
        while srch:
            s = s.replace(
                srch.group("word"), srch.group("word").replace("-", "\u2011")
            )  # non-breaking hyphen
            srch = re_nbh.search(s)
    return s


def replace_no_break(s, spaces=True, hyphens=True):
    spans = iter_url_spans(s)
    if not spans:
        return _replace_no_break_segment(s, spaces=spaces, hyphens=hyphens)

    chunks = []
    pos = 0
    for start, end in spans:
        if start < pos:
            continue
        chunks.append(_replace_no_break_segment(s[pos:start], spaces, hyphens))
        chunks.append(s[start:end])
        pos = end
    chunks.append(_replace_no_break_segment(s[pos:], spaces, hyphens))
    return "".join(chunks)


def detect_accent(s):
    for word in re.split(
        r"[^{}{}]+".format("".join(LOWERCASE_RUSSIAN), "".join(UPPERCASE_RUSSIAN)), s
    ):
        if word.upper() != word and len(word) > 1:
            try:
                i = 1
                word_new = word
                while i < len(word_new):
                    if (
                        word_new[i] in POTENTIAL_ACCENTS
                        and word_new[:i] not in BAD_BEGINNINGS
                        and (i == 1 or not word_new[i - 1].isupper())
                        and (i + 1 == len(word_new) or not word_new[i + 1].isupper())
                    ):
                        word_new = (
                            word_new[:i]
                            + word_new[i].lower()
                            + "\u0301"
                            + word_new[i + 1 :]
                        )
                    i += 1
                if word != word_new:
                    s = s[: s.index(word)] + word_new + s[s.index(word) + len(word) :]
            except Exception:
                logger.exception(f"error while trying to process word {word!r}")
    return s


def percent_decode(s):
    grs = sorted(
        [match.group(0) for match in re_percent.finditer(s)], key=len, reverse=True
    )
    for gr in grs:
        try:
            s = s.replace(gr, unquote(gr.encode("utf8")).decode("utf8"))
        except Exception:
            logger.exception(f"error while trying to replace percents in {gr}")
    return s


def recursive_typography(s, **kwargs):
    if isinstance(s, str):
        s = typography(s, **kwargs)
        return s
    elif isinstance(s, list):
        new_s = []
        for element in s:
            new_s.append(recursive_typography(element, **kwargs))
        return new_s


RE_BAD_CYR_QUOTES = re.compile("“[а-яА-ЯЁё0-9,\\.:!\\? ]+?”")
RE_BAD_LAT_QUOTES = re.compile("'[a-zA-Z0-9,\\.:!\\? ]+?'")
RE_BAD_LAT_DQUOTES = re.compile('"[a-zA-Z0-9,\\.:!\\? ]+?"')


def typography(s, wsp="on", quotes="on", dashes="on", accents="on", percent="on"):
    wsp = wsp or "on"
    quotes = quotes or "on"
    dashes = dashes or "on"
    accents = accents or "on"
    percent = percent or "on"
    if wsp == "on":
        s = remove_excessive_whitespace(s)
    if quotes in ("on", "smart"):
        s = get_quotes_right(s)
    if quotes == "on" or quotes.startswith("smart") and "'s" in s:
        s = s.replace("'s", "’s")
    if quotes.startswith("smart"):
        srch = RE_BAD_CYR_QUOTES.search(s)
        if "«" in s:
            fix_start = "„"
            fix_end = "“"
        else:
            fix_start = "«"
            fix_end = "»"
        while srch:
            grp = srch.group(0)
            s = s.replace(grp, fix_start + grp[1:-1] + fix_end)
            srch = RE_BAD_CYR_QUOTES.search(s)
        srch = RE_BAD_LAT_QUOTES.search(s)
        while srch:
            grp = srch.group(0)
            s = s.replace(grp, "‘" + grp[1:-1] + "’")
            srch = RE_BAD_CYR_QUOTES.search(s)
        srch = RE_BAD_LAT_DQUOTES.search(s)
        while srch:
            grp = srch.group(0)
            s = s.replace(grp, "“" + grp[1:-1] + "”")
            srch = RE_BAD_LAT_DQUOTES.search(s)
    if dashes == "on":
        s = get_dashes_right(s)
    if accents in ("on", "light") or accents.startswith("smart"):
        s = fix_accents_func(s, mode=accents)
    if percent:
        s = percent_decode(s)
    return s


def matching_bracket(s):
    assert s in OPENING_BRACKETS or s in CLOSING_BRACKETS
    if s in OPENING_BRACKETS:
        return CLOSING_BRACKETS[OPENING_BRACKETS.index(s)]
    return OPENING_BRACKETS[CLOSING_BRACKETS.index(s)]


def find_matching_closing_bracket(s, index):
    s = list(s)
    i = index
    assert s[i] in OPENING_BRACKETS
    ob = s[i]
    cb = matching_bracket(ob)
    counter = 0
    while i < len(s):
        if s[i] == ob:
            counter += 1
        if s[i] == cb:
            counter -= 1
            if counter == 0:
                return i
        i += 1
    return None


def find_matching_opening_bracket(s, index):
    s = list(s)
    i = index
    assert s[i] in CLOSING_BRACKETS
    cb = s[i]
    ob = matching_bracket(cb)
    counter = 0
    if i < 0:
        i = len(s) - abs(i)
    while i < len(s) and i >= 0:
        if s[i] == cb:
            counter += 1
        if s[i] == ob:
            counter -= 1
            if counter == 0:
                return i
        i -= 1
    return None
