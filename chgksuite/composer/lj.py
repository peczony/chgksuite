import codecs
import datetime
import os
import random
import re
import sys
import time
import traceback
from xmlrpc.client import ServerProxy

from chgksuite.common import log_wrap, retry_wrapper_factory
from chgksuite.composer.chgksuite_parser import find_heading, find_tour
from chgksuite.composer.composer_common import (
    IMGUR_CLIENT_ID,
    BaseExporter,
    Imgur,
    md5,
    parseimg,
)
from chgksuite.typotools import re_lowercase, re_uppercase


class LjExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lj = ServerProxy("http://www.livejournal.com/interface/xmlrpc").LJ.XMLRPC
        self.im = Imgur(self.args.imgur_client_id or IMGUR_CLIENT_ID)
        self.retry_wrapper = retry_wrapper_factory(self.logger)

    def get_chal(self):
        chal = None
        chal = self.retry_wrapper(self.lj.getchallenge)["challenge"]
        response = md5(
            chal.encode("utf8") + md5(self.args.password.encode("utf8")).encode("utf8")
        )
        return (chal, response)

    def split_into_tours(self):
        general_impression = self.args.genimp
        result = []
        current = []
        mode = "meta"
        for _, element in enumerate(self.structure):
            if element[0] != "Question":
                if mode == "meta":
                    current.append(element)
                elif element[0] == "section":
                    result.append(current)
                    current = [element]
                    mode = "meta"
                else:
                    current.append(element)
            else:
                if mode == "meta":
                    current.append(element)
                    mode = "questions"
                else:
                    current.append(element)
        result.append(current)
        globalheading = find_heading(result[0])[1][1]
        globalsep = "." if not globalheading.endswith(".") else ""
        currentheading = result[0][find_heading(result[0])[0]][1]
        result[0][find_heading(result[0])[0]][1] += "{} {}".format(
            "." if not currentheading.endswith(".") else "", find_tour(result[0])[1][1]
        )
        for tour in result[1:]:
            if not find_heading(tour):
                tour.insert(
                    0,
                    [
                        "ljheading",
                        "{}{} {}".format(
                            globalheading, globalsep, find_tour(tour)[1][1]
                        ),
                    ],
                )
        if general_impression:
            result.append(
                [
                    [
                        "ljheading",
                        "{}{} {}".format(
                            globalheading,
                            globalsep,
                            self.labels["general"]["general_impressions_caption"],
                        ),
                    ],
                    ["meta", self.labels["general"]["general_impressions_text"]],
                ]
            )
        return result

    def _lj_post(self, stru, edit=False, add_params=None):
        now = datetime.datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        day = now.strftime("%d")
        hour = now.strftime("%H")
        minute = now.strftime("%M")

        chal, response = self.get_chal()

        params = {
            "username": self.args.login,
            "auth_method": "challenge",
            "auth_challenge": chal,
            "auth_response": response,
            "subject": stru["header"],
            "event": stru["content"],
            "year": year,
            "mon": month,
            "day": day,
            "hour": hour,
            "min": minute,
        }
        if edit:
            params["itemid"] = stru["itemid"]
        if add_params:
            params.update(add_params)

        try:
            post = self.retry_wrapper(
                self.lj.editevent if edit else self.lj.postevent, [params]
            )
            self.logger.info("Edited a post" if edit else "Created a post")
            self.logger.debug(log_wrap(post))
            time.sleep(5)
        except Exception as e:
            sys.stderr.write(
                "Error issued by LJ API: {}".format(traceback.format_exc(e))
            )
            sys.exit(1)
        return post

    def _lj_comment(self, stru):
        chal, response = self.get_chal()
        params = {
            "username": self.args.login,
            "auth_method": "challenge",
            "auth_challenge": chal,
            "auth_response": response,
            "journal": stru["journal"],
            "ditemid": stru["ditemid"],
            "parenttalkid": 0,
            "body": stru["content"],
            "subject": stru["header"],
        }
        try:
            comment = self.retry_wrapper(self.lj.addcomment, [params])
        except Exception as e:
            sys.stderr.write(
                "Error issued by LJ API: {}".format(traceback.format_exc(e))
            )
            sys.exit(1)
        self.logger.info("Added a comment")
        self.logger.debug(log_wrap(comment))
        time.sleep(random.randint(7, 12))

    def lj_post(self, stru, edit=False):
        add_params = {}
        community = self.args.community
        if community:
            add_params["usejournal"] = community
        elif self.args.security == "public":
            pass
        elif self.args.security:
            add_params["security"] = "usemask"
            add_params["allowmask"] = (
                "1" if self.args.security == "friends" else self.args.security
            )
        else:
            add_params["security"] = "private"

        journal = community if community else self.args.login

        post = self._lj_post(stru[0], edit=edit, add_params=add_params)

        comments = stru[1:]

        if not comments:
            return post

        for comment in stru[1:]:
            comment["ditemid"] = post["ditemid"]
            comment["journal"] = journal
            self._lj_comment(comment)

        return post

    def lj_process(self, structure):
        final_structure = [{"header": "", "content": ""}]
        i = 0
        heading = ""
        ljheading = ""

        def yapper(x):
            return self.htmlyapper(x)

        while i < len(structure) and structure[i][0] != "Question":
            if structure[i][0] == "heading":
                final_structure[0]["content"] += "<center>{}</center>".format(
                    yapper(structure[i][1])
                )
                heading = yapper(structure[i][1])
            if structure[i][0] == "ljheading":
                # final_structure[0]['header'] = structure[i][1]
                ljheading = yapper(structure[i][1])
            if structure[i][0] == "date":
                final_structure[0]["content"] += "\n<center>{}</center>".format(
                    yapper(structure[i][1])
                )
            if structure[i][0] == "editor":
                final_structure[0]["content"] += "\n<center>{}</center>".format(
                    yapper(structure[i][1])
                )
            if structure[i][0] == "meta":
                final_structure[0]["content"] += "\n{}".format(yapper(structure[i][1]))
            i += 1

        if ljheading != "":
            final_structure[0]["header"] = ljheading
        else:
            final_structure[0]["header"] = heading

        for element in structure[i:]:
            if element[0] == "Question":
                formatted = self.get_label(element[1], "question", number=self.counter)
                final_structure.append(
                    {
                        "header": formatted,
                        "content": self.html_format_question(element[1]),
                    }
                )
                self.counter += 1
            if element[0] == "meta":
                final_structure.append({"header": "", "content": yapper(element[1])})

        if not final_structure[0]["content"]:
            final_structure[0]["content"] = self.labels["general"][
                "general_impressions_text"
            ]
        if self.args.debug:
            with codecs.open("lj.debug", "w", "utf8") as f:
                f.write(log_wrap(final_structure))
        return final_structure

    def htmlyapper(self, e, replace_spaces=True):
        if isinstance(e, str):
            return self.html_element_layout(e, replace_spaces=replace_spaces)
        elif isinstance(e, list):
            if not any(isinstance(x, list) for x in e):
                return self.html_element_layout(e, replace_spaces=replace_spaces)
            else:
                return "\n".join(
                    [
                        self.html_element_layout(x, replace_spaces=replace_spaces)
                        for x in e
                    ]
                )

    def html_element_layout(self, e, replace_spaces=True):
        res = ""
        if isinstance(e, str):
            res = self.htmlformat(e, replace_spaces=replace_spaces)
            return res
        if isinstance(e, list):
            res = "\n".join(
                [
                    "{}. {}".format(
                        en + 1,
                        self.html_element_layout(x, replace_spaces=replace_spaces),
                    )
                    for en, x in enumerate(e)
                ]
            )
            return res

    def html_format_question(self, q):
        def yapper(x, **kwargs):
            return self.htmlyapper(x, **kwargs)

        if "setcounter" in q:
            self.counter = int(q["setcounter"])
        res = "<strong>{question}.</strong> {content}".format(
            question=self.get_label(q, "question", self.counter),
            content=yapper(q["question"])
            + ("\n<lj-spoiler>" if not self.args.nospoilers else ""),
        )
        if "number" not in q:
            self.counter += 1
        for field in ("answer", "zachet", "nezachet", "comment", "source", "author"):
            if field in q:
                res += "\n<strong>{field}: </strong>{content}".format(
                    field=self.get_label(q, field),
                    content=yapper(q[field], replace_spaces=field != "source"),
                )
        if not self.args.nospoilers:
            res += "</lj-spoiler>"
        return res

    @staticmethod
    def htmlrepl(zz):
        zz = zz.replace("&", "&amp;")
        zz = zz.replace("<", "&lt;")
        zz = zz.replace(">", "&gt;")

        while "`" in zz:
            if zz.index("`") + 1 >= len(zz):
                zz = zz.replace("`", "")
            else:
                if zz.index("`") + 2 < len(zz) and re.search(
                    r"\s", zz[zz.index("`") + 2]
                ):
                    zz = zz[: zz.index("`") + 2] + "" + zz[zz.index("`") + 2 :]
                if zz.index("`") + 1 < len(zz) and re_lowercase.search(
                    zz[zz.index("`") + 1]
                ):
                    zz = (
                        zz[: zz.index("`") + 1]
                        + ""
                        + zz[zz.index("`") + 1]
                        + "&#x0301;"
                        + zz[zz.index("`") + 2 :]
                    )
                elif zz.index("`") + 1 < len(zz) and re_uppercase.search(
                    zz[zz.index("`") + 1]
                ):
                    zz = (
                        zz[: zz.index("`") + 1]
                        + ""
                        + zz[zz.index("`") + 1]
                        + "&#x0301;"
                        + zz[zz.index("`") + 2 :]
                    )
                zz = zz[: zz.index("`")] + zz[zz.index("`") + 1 :]

        return zz

    def htmlformat(self, s, replace_spaces=True):
        res = ""
        for run in self.parse_4s_elem(s):
            if run[0] == "screen":
                res += self.htmlrepl(run[1]["for_screen"])
            elif run[0] == "pagebreak":
                pass
            elif run[0] == "strike":
                res += "<s>" + self.htmlrepl(run[1]) + "</s>"
            elif run[0] == "bold":
                res += "<b>" + self.htmlrepl(run[1]) + "</b>"
            elif run[0] == "underline":
                res += "<u>" + self.htmlrepl(run[1]) + "</u>"
            elif run[0] == "italic":
                res += "<em>" + self.htmlrepl(run[1]) + "</em>"
            elif run[0] == "linebreak":
                res += "<br>"
            elif run[0] == "img":
                parsed_image = parseimg(
                    run[1],
                    dimensions="pixels",
                    targetdir=self.dir_kwargs.get("targetdir"),
                    tmp_dir=self.dir_kwargs.get("tmp_dir"),
                )
                imgfile = parsed_image["imgfile"]
                w = parsed_image["width"]
                h = parsed_image["height"]
                if os.path.isfile(imgfile):
                    uploaded_image = self.im.upload_image(imgfile, title=imgfile)
                    imgfile = uploaded_image["data"]["link"]

                res += '<img{}{} src="{}"/>'.format(
                    "" if w == -1 else " width={}".format(w),
                    "" if h == -1 else " height={}".format(h),
                    imgfile,
                )
            else:
                res += self.htmlrepl(run[1])
        if replace_spaces:
            res = self._replace_no_break(res)
        return res

    @staticmethod
    def generate_navigation(strus):
        titles = [x[0][0]["header"].split(". ")[-1] for x in strus]
        urls = [x[1]["url"] for x in strus]
        result = []
        for i in range(len(titles)):
            inner = []
            for j in range(len(urls)):
                inner.append(
                    titles[j]
                    if j == i
                    else '<a href="{}">{}</a>'.format(urls[j], titles[j])
                )
            result.append(" | ".join(inner))
        return result

    def export(self):
        args = self.args
        if not args.community:
            args.community = ""
        if not args.login:
            print("Login not specified.")
            sys.exit(1)
        elif not args.password:
            import getpass

            args.password = getpass.getpass()

        self.counter = 1
        if args.splittours:
            tours = self.split_into_tours()
            strus = []
            for tour in tours:
                stru = self.lj_process(tour)
                post = self.lj_post(stru)
                strus.append((stru, post))
            if args.navigation:
                navigation = self.generate_navigation(strus)
                for i, (stru, post) in enumerate(strus):
                    newstru = {
                        "header": stru[0]["header"],
                        "content": stru[0]["content"] + "\n\n" + navigation[i],
                        "itemid": post["itemid"],
                    }
                    self.lj_post([newstru], edit=True)
        else:
            stru = self.lj_process(self.structure)
            post = self.lj_post(stru)
