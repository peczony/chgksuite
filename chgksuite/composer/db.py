import codecs
import datetime
import os
import re

import dateparser
import pyperclip
from PIL import Image

from chgksuite.common import replace_escaped
from chgksuite.composer.chgksuite_parser import check_if_zero
from chgksuite.composer.composer_common import (
    IMGUR_CLIENT_ID,
    BaseExporter,
    Imgur,
    parseimg,
)

re_editors = re.compile(r"^[рР]едакторы? *(пакета|тура)? *[—\-–−:] ?")


class DbExporter(BaseExporter):
    BASE_MAPPING = {
        "section": "Тур",
        "heading": "Чемпионат",
        "editor": "Редактор",
        "meta": "Инфо",
    }
    re_date_sep = re.compile(" [—–-] ")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.qcount = 0
        self.im = Imgur(self.args.imgur_client_id or IMGUR_CLIENT_ID)

    def baseyapper(self, e):
        if isinstance(e, str):
            return self.base_element_layout(e)
        elif isinstance(e, list):
            if not any(isinstance(x, list) for x in e):
                return self.base_element_layout(e)
            else:
                return "\n".join([self.base_element_layout(x) for x in e])

    def parse_and_upload_image(self, path):
        parsed_image = parseimg(
            path,
            dimensions="pixels",
            targetdir=self.dir_kwargs.get("targetdir"),
            tmp_dir=self.dir_kwargs.get("tmp_dir"),
        )
        imgfile = parsed_image["imgfile"]
        w = parsed_image["width"]
        h = parsed_image["height"]
        pil_image = Image.open(imgfile)
        w_orig, h_orig = pil_image.size
        if w_orig != w or h_orig != h:
            self.logger.info("resizing image {}".format(imgfile))
            pil_image = pil_image.resize((int(w), int(h)), resample=Image.LANCZOS)
            bn, _ = os.path.splitext(imgfile)
            resized_fn = "{}_resized.png".format(bn)
            pil_image.save(resized_fn, "PNG")
            to_upload = resized_fn
        else:
            to_upload = imgfile
        self.logger.info("uploading {}...".format(to_upload))
        uploaded_image = self.im.upload_image(to_upload, title=to_upload)
        imglink = uploaded_image["data"]["link"]
        self.logger.info("the link for {} is {}...".format(to_upload, imglink))
        return imglink

    def baseformat(self, s):
        res = ""
        for run in self.parse_4s_elem(s):
            if run[0] in ("", "hyperlink"):
                res += run[1].replace("\n", "\n   ")
            if run[0] == "em":
                res += run[1]
            if run[0] == "screen":
                res += run[1]["for_print"]
            if run[0] == "img":
                if run[1].startswith(("http://", "https://")):
                    imglink = run[1]
                else:
                    imglink = self.parse_and_upload_image(run[1])
                res += "(pic: {})".format(imglink)
        while res.endswith("\n"):
            res = res[:-1]
        res = replace_escaped(res)
        return res

    def base_element_layout(self, e):
        res = ""
        if isinstance(e, str):
            if self.args.remove_accents:
                for match in re.finditer("(.)\u0301", e):
                    replacement = match.group(1).upper()
                    e = e.replace(match.group(0), replacement)
            res = self.baseformat(e)
            return res
        if isinstance(e, list):
            res = "\n".join(
                [
                    "   {}. {}".format(i + 1, self.base_element_layout(x))
                    for i, x in enumerate(e)
                ]
            )
        return res

    def wrap_date(self, s):
        s = s.strip()
        parsed = dateparser.parse(s)
        if isinstance(parsed, datetime.datetime):
            parsed = parsed.date()
        if not parsed:
            self.logger.error(
                "unable to parse date {}, setting to default 2010-01-01".format(s)
            )
            return datetime.date(2010, 1, 1).strftime("%d-%b-%Y")
        if parsed > datetime.date.today():
            parsed = parsed.replace(year=parsed.year - 1)
        formatted = parsed.strftime("%d-%b-%Y")
        return formatted

    def base_format_element(self, pair):
        if pair[0] == "Question":
            return self.base_format_question(pair[1])
        if pair[0] in self.BASE_MAPPING:
            return "{}:\n{}\n\n".format(
                self.BASE_MAPPING[pair[0]], self.baseyapper(pair[1])
            )
        elif pair[0] == "date":
            re_search = self.re_date_sep.search(pair[1])
            if re_search:
                gr0 = re_search.group(0)
                dates = pair[1].split(gr0)
                return "Дата:\n{} - {}\n\n".format(
                    self.wrap_date(dates[0]), self.wrap_date(dates[-1])
                )
            else:
                return "Дата:\n{}\n\n".format(self.wrap_date(pair[1]))

    @staticmethod
    def _get_last_value(dct, key):
        if isinstance(dct[key], list):
            return dct[key][-1]
        return dct[key]

    @staticmethod
    def _add_to_dct(dct, key, to_add):
        if isinstance(dct[key], list):
            dct[key][-1] += to_add
        else:
            dct[key] += to_add

    def base_format_question(self, q):
        if "setcounter" in q:
            self.qcount = int(q["setcounter"])
        res = "Вопрос {}:\n{}\n\n".format(
            self.qcount if "number" not in q else q["number"],
            self.baseyapper(q["question"]),
        )
        if "number" not in q:
            self.qcount += 1
        res += "Ответ:\n{}\n\n".format(self.baseyapper(q["answer"]))
        if "zachet" in q:
            res += "Зачет:\n{}\n\n".format(self.baseyapper(q["zachet"]))
        if "nezachet" in q:
            res += "Незачет:\n{}\n\n".format(self.baseyapper(q["zachet"]))
        if "comment" in q:
            res += "Комментарий:\n{}\n\n".format(self.baseyapper(q["comment"]))
        if "source" in q:
            res += "Источник:\n{}\n\n".format(self.baseyapper(q["source"]))
        if "author" in q:
            res += "Автор:\n{}\n\n".format(self.baseyapper(q["author"]))
        return res

    def export(self, outfilename):
        result = []
        lasttour = 0
        zeroq = 1
        for i, pair in enumerate(self.structure):
            if pair[0] == "section":
                lasttour = i
            while (
                pair[0] == "meta"
                and (i + 1) < len(self.structure)
                and self.structure[i + 1][0] == "meta"
            ):
                pair[1] += "\n{}".format(self.structure[i + 1][1])
                self.structure.pop(i + 1)
            if pair[0] == "Question" and check_if_zero(pair[1]):
                tourheader = "Нулевой вопрос {}".format(zeroq)
                zeroq += 1
                pair[1]["number"] = 1
                self.structure.insert(lasttour, self.structure.pop(i))
                self.structure.insert(lasttour, ["section", tourheader])
        for pair in self.structure:
            if pair[0] == "Question" and "nezachet" in pair[1]:
                field = "zachet" if "zachet" in pair[1] else "answer"
                last_val = self._get_last_value(pair[1], field)
                nezachet = self.baseyapper(pair[1].pop("nezachet"))
                to_add = "{}\n   Незачёт: {}".format(
                    "." if not last_val.endswith(".") else "", nezachet
                )
                self._add_to_dct(pair[1], field, to_add)
            if pair[0] == "editor":
                pair[1] = re.sub(re_editors, "", pair[1])
                self.logger.info('Поле "Редактор" было автоматически изменено.')
            res = self.base_format_element(pair)
            if res:
                result.append(res)
        text = "".join(result)
        with codecs.open(outfilename, "w", "utf8") as f:
            f.write(text)
        self.logger.info("Output: {}".format(outfilename))
        if self.args.clipboard:
            pyperclip.copy(text)
