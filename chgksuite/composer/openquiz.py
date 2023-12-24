import codecs
import copy
import re
import json
import os

from chgksuite.composer.composer_common import (
    IMGUR_CLIENT_ID,
    BaseExporter,
    Imgur,
    parseimg,
)
from chgksuite.typotools import replace_no_break_spaces

MEDIA_STUB = {"Key": "", "Type": "Picture"}

OQ_STUB = {
    "Single": {
        "Caption": "31",
        "Question": {},
        "QuestionMedia": None,
        "Answer": {"OpenAnswer": ""},
        "AnswerMedia": None,
        "Comment": "",
        "Points": "1",
        "JeopardyPoints": None,
        "WithChoice": False,
        "Seconds": None,
        "EndOfTour": False,
    }
}


class OpenquizExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.im = Imgur(self.args.imgur_client_id or IMGUR_CLIENT_ID)
        self.qcount = 1

    def parse_and_upload_image(self, path):
        parsed_image = parseimg(
            path,
            dimensions="ems",
            targetdir=self.dir_kwargs.get("targetdir"),
            tmp_dir=self.dir_kwargs.get("tmp_dir"),
        )
        imgfile = parsed_image["imgfile"]
        if os.path.isfile(imgfile):
            uploaded_image = self.im.upload_image(imgfile, title=imgfile)
            imglink = uploaded_image["data"]["link"]
            return imglink

    def oqformat(self, s):
        res = ""
        images = []
        s = self.remove_square_brackets(s)
        for run in self.parse_4s_elem(s):
            if run[0] in ("", "hyperlink", "italic"):
                res += run[1]
            elif run[0] == "screen":
                res += run[1]["for_screen"]
            elif run[0] == "img":
                if run[1].startswith(("http://", "https://")):
                    imglink = run[1]
                else:
                    imglink = self.parse_and_upload_image(run[1])
                images.append(imglink)
            else:
                self.logger.info(
                    f"element type `{run[0]}` won't be rendered in openquiz"
                )
        while res.endswith("\n"):
            res = res[:-1]
        hs = self.labels["question_labels"]["handout_short"]
        if images:
            res = re.sub("\\[" + hs + "(.+?)\\]", "", s, flags=re.DOTALL)
            res = res.strip()
        elif hs in res:
            re_hs = re.search("\\[" + hs + ".+?: ?(.+)\\]", res, flags=re.DOTALL)
            if re_hs:
                res = res.replace(re_hs.group(0), re_hs.group(1))
        res = res.replace("\n", "  \n")
        res = replace_no_break_spaces(res)
        res = res.replace("\u0301", "")
        return (res, images)

    def make_split(self, question, join=False):
        result = None
        if isinstance(question, list):
            if len(question) == 1:
                result = question[0]
            if isinstance(question[1], list):
                inner_list = question[1]
                inner_list = [f"{i + 1}. {s}" for i, s in enumerate(inner_list)]
                inner_list[0] = question[0] + "\n" + inner_list[0]
                result = inner_list
            else:
                inner_list = [f"{i + 1}. {s}" for i, s in enumerate(question[1])]
                result = inner_list
        else:
            result = question
        if join and isinstance(result, list):
            return "\n".join(result)
        else:
            return result

    def oq_format_question(self, question):
        result = copy.deepcopy(OQ_STUB)
        split = self.make_split(question["question"])
        if isinstance(split, list):
            question_images = []
            for i, s in enumerate(split):
                tup = self.oqformat(s)
                split[i] = tup[0]
                question_images.extend(tup[1])
            result["Single"]["Question"]["Split"] = split
        else:
            split, question_images = self.oqformat(split)
            result["Single"]["Question"]["Solid"] = split
        if question_images:
            result["Single"]["QuestionMedia"] = MEDIA_STUB.copy()
            result["Single"]["QuestionMedia"]["Key"] = question_images[0]
            if len(question_images) > 1:
                self.logger.info(
                    f"В вопросе {question['number']} больше одной картинки-раздатки, отобразится только первая"
                )
        answer = self.make_split(question["answer"], join=True)
        if "zachet" in question:
            zachet = self.make_split(question["zachet"], join=True)
            answer += "\n" + zachet
        answer_images = []
        formatted, images = self.oqformat(answer)
        answer_images.extend(images)
        result["Single"]["Answer"]["OpenAnswer"] = formatted
        if "comment" in question:
            comment = self.make_split(question["comment"], join=True)
            formatted, images = self.oqformat(comment)
            answer_images.extend(images)
            result["Single"]["Comment"] = formatted
        if answer_images:
            result["Single"]["AnswerMedia"] = MEDIA_STUB.copy()
            result["Single"]["AnswerMedia"]["Key"] = answer_images[0]
            if len(answer_images) > 1:
                self.logger.info(
                    f"В вопросе {question['number']} больше одной картинки-раздатки на ответ, отобразится только первая"
                )
        result["Single"]["Caption"] = str(question["number"])
        if question.get("end_of_tour"):
            result["Single"]["EndOfTour"] = True
        return result

    def export(self, outfilename):
        questions_tours = [q for q in self.structure if q[0] in ("Question", "tour")]
        for i, el in enumerate(questions_tours):
            if i + 1 == len(questions_tours) or questions_tours[i + 1][0] == "tour":
                el[1]["end_of_tour"] = True
        questions = [q[1] for q in questions_tours if q[0] == "Question"]
        result = []
        for q in questions:
            result.append(self.oq_format_question(q))
        with codecs.open(outfilename, "w", "utf8") as f:
            f.write(json.dumps(result, indent=2, ensure_ascii=False))
