import os

from chgksuite.composer.composer_common import (
    IMGUR_CLIENT_ID,
    BaseExporter,
    Imgur,
    parseimg,
)


class MarkdownExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.im = Imgur(self.args.imgur_client_id or IMGUR_CLIENT_ID)
        self.qcount = 1

    def markdownyapper(self, e):
        if isinstance(e, str):
            return self.markdown_element_layout(e)
        elif isinstance(e, list):
            if not any(isinstance(x, list) for x in e):
                return self.markdown_element_layout(e)
            else:
                return "  \n".join([self.markdown_element_layout(x) for x in e])

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

    def markdownformat(self, s):
        res = ""
        for run in self.parse_4s_elem(s):
            if run[0] == "":
                res += run[1]
            if run[0] == "hyperlink":
                res += f"<{run[1]}>"
            if run[0] == "screen":
                res += run[1]["for_screen"]
            if run[0] == "italic":
                res += f"_{run[1]}_"
            if run[0] == "img":
                if run[1].startswith(("http://", "https://")):
                    imglink = run[1]
                else:
                    imglink = self.parse_and_upload_image(run[1])
                if self.args.filetype == "redditmd":
                    res += f"[картинка]({imglink})"
                else:
                    res += f"![]({imglink})"
        while res.endswith("\n"):
            res = res[:-1]
        res = res.replace("\n", "  \n")
        return res

    def markdown_element_layout(self, e):
        res = ""
        if isinstance(e, str):
            res = self.markdownformat(e)
            return res
        if isinstance(e, list):
            res = "  \n".join(
                [
                    f"{i + 1}\\. {self.markdown_element_layout(x)}"
                    for i, x in enumerate(e)
                ]
            )
        return res

    def markdown_format_element(self, pair):
        if pair[0] == "Question":
            return self.markdown_format_question(pair[1])

    def markdown_format_question(self, q):
        if "setcounter" in q:
            self.qcount = int(q["setcounter"])
        res = "__Вопрос {}__: {}  \n".format(
            q.get("number", self.qcount),
            self.markdownyapper(q["question"]),
        )
        if "number" not in q:
            self.qcount += 1
        spoiler_start = ">!" if self.args.filetype == "redditmd" else ""
        spoiler_end = "!<" if self.args.filetype == "redditmd" else ""
        res += "__Ответ:__ {}{}  \n".format(
            spoiler_start, self.markdownyapper(q["answer"])
        )
        if "zachet" in q:
            res += "__Зачёт:__ {}  \n".format(self.markdownyapper(q["zachet"]))
        if "nezachet" in q:
            res += "__Незачёт:__ {}  \n".format(self.markdownyapper(q["nezachet"]))
        if "comment" in q:
            res += "__Комментарий:__ {}  \n".format(self.markdownyapper(q["comment"]))
        if "source" in q:
            res += "__Источник:__ {}  \n".format(self.markdownyapper(q["source"]))
        if "author" in q:
            res += "{}\n__Автор:__ {}  \n".format(
                spoiler_end, self.markdownyapper(q["author"])
            )
        else:
            res += spoiler_end + "\n"
        return res

    def export(self, outfile):
        result = []
        for pair in self.structure:
            res = self.markdown_format_element(pair)
            if res:
                result.append(res)
        text = "\n\n".join(result)
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(text)
        self.logger.info(f"Output: {outfile}")
