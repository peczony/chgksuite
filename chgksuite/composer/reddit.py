import codecs
import os

from chgksuite.composer.composer_common import (
    IMGUR_CLIENT_ID,
    BaseExporter,
    Imgur,
    parseimg,
)


class RedditExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.im = Imgur(self.args.imgur_client_id or IMGUR_CLIENT_ID)
        self.qcount = 1

    def reddityapper(self, e):
        if isinstance(e, str):
            return self.reddit_element_layout(e)
        elif isinstance(e, list):
            if not any(isinstance(x, list) for x in e):
                return self.reddit_element_layout(e)
            else:
                return "  \n".join([self.reddit_element_layout(x) for x in e])

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

    def redditformat(self, s):
        res = ""
        for run in self.parse_4s_elem(s):
            if run[0] in ("", "hyperlink"):
                res += run[1]
            if run[0] == "screen":
                res += run[1]["for_screen"]
            if run[0] == "italic":
                res += "_{}_".format(run[1])
            if run[0] == "img":
                if run[1].startswith(("http://", "https://")):
                    imglink = run[1]
                else:
                    imglink = self.parse_and_upload_image(run[1])
                res += "[картинка]({})".format(imglink)
        while res.endswith("\n"):
            res = res[:-1]
        res = res.replace("\n", "  \n")
        return res

    def reddit_element_layout(self, e):
        res = ""
        if isinstance(e, str):
            res = self.redditformat(e)
            return res
        if isinstance(e, list):
            res = "  \n".join(
                [
                    "{}\\. {}".format(i + 1, self.reddit_element_layout(x))
                    for i, x in enumerate(e)
                ]
            )
        return res

    def reddit_format_element(self, pair):
        if pair[0] == "Question":
            return self.reddit_format_question(pair[1])

    def reddit_format_question(self, q):
        if "setcounter" in q:
            self.qcount = int(q["setcounter"])
        res = "__Вопрос {}__: {}  \n".format(
            self.qcount if "number" not in q else q["number"],
            self.reddityapper(q["question"]),
        )
        if "number" not in q:
            self.qcount += 1
        res += "__Ответ:__ >!{}  \n".format(self.reddityapper(q["answer"]))
        if "zachet" in q:
            res += "__Зачёт:__ {}  \n".format(self.reddityapper(q["zachet"]))
        if "nezachet" in q:
            res += "__Незачёт:__ {}  \n".format(self.reddityapper(q["nezachet"]))
        if "comment" in q:
            res += "__Комментарий:__ {}  \n".format(self.reddityapper(q["comment"]))
        if "source" in q:
            res += "__Источник:__ {}  \n".format(self.reddityapper(q["source"]))
        if "author" in q:
            res += "!<\n__Автор:__ {}  \n".format(self.reddityapper(q["author"]))
        else:
            res += "!<\n"
        return res

    def export(self, outfile):
        result = []
        for pair in self.structure:
            res = self.reddit_format_element(pair)
            if res:
                result.append(res)
        text = "\n\n".join(result)
        with codecs.open(outfile, "w", "utf8") as f:
            f.write(text)
        self.logger.info("Output: {}".format(outfile))
