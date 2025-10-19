import codecs
import hashlib
import os
import re
import shlex
import shutil
import subprocess

import chgksuite.typotools as typotools
from chgksuite.composer.composer_common import BaseExporter, parseimg
from chgksuite.typotools import re_lowercase, re_uppercase, re_url

re_scaps = re.compile(r"(^|[\s])([\[\]\(\)«»А-Я \u0301`ЁA-Z]{2,})([\s,!\.;:-\?]|$)")


class LatexExporter(BaseExporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.qcount = 0

    def tex_format_question(self, q):
        if "setcounter" in q:
            self.qcount = int(q["setcounter"])
        res = (
            "\n\n\\begin{{minipage}}{{\\textwidth}}\\raggedright\n"
            "\\textbf{{Вопрос {}.}} {} \\newline".format(
                self.qcount if "number" not in q else q["number"],
                self.texyapper(q["question"]),
            )
        )
        if "number" not in q:
            self.qcount += 1
        res += "\n\\textbf{{Ответ: }}{} \\newline".format(self.texyapper(q["answer"]))
        if "zachet" in q:
            res += "\n\\textbf{{Зачёт: }}{} \\newline".format(
                self.texyapper(q["zachet"])
            )
        if "nezachet" in q:
            res += "\n\\textbf{{Незачёт: }}{} \\newline".format(
                self.texyapper(q["nezachet"])
            )
        if "comment" in q:
            res += "\n\\textbf{{Комментарий: }}{} \\newline".format(
                self.texyapper(q["comment"])
            )
        if "source" in q:
            res += "\n\\textbf{{Источник{}: }}{} \\newline".format(
                "и" if isinstance(q["source"], list) else "",
                self.texyapper(q["source"]),
            )
        if "author" in q:
            res += "\n\\textbf{{Автор: }}{} \\newline".format(
                self.texyapper(q["author"])
            )
        res += "\n\\end{minipage}\n"
        return res

    @staticmethod
    def texrepl(zz):
        zz = re.sub(r"{", r"\{", zz)
        zz = re.sub(r"}", r"\}", zz)
        zz = re.sub(r"\\(?![\}\{])", r"{\\textbackslash}", zz)
        zz = re.sub("%", "\\%", zz)
        zz = re.sub(r"\$", "\\$", zz)
        zz = re.sub("#", "\\#", zz)
        zz = re.sub("&", "\\&", zz)
        zz = re.sub("_", r"\_", zz)
        zz = re.sub(r"\^", r"{\\textasciicircum}", zz)
        zz = re.sub(r"\~", r"{\\textasciitilde}", zz)
        zz = re.sub(r'((\"(?=[ \.\,;\:\?!\)\]]))|("(?=\Z)))', "»", zz)
        zz = re.sub(r'(((?<=[ \.\,;\:\?!\(\[)])")|((?<=\A)"))', "«", zz)
        zz = re.sub('"', "''", zz)

        for match in sorted(
            [x for x in re_scaps.finditer(zz)],
            key=lambda x: len(x.group(2)),
            reverse=True,
        ):
            zz = zz.replace(match.group(2), "\\tsc{" + match.group(2).lower() + "}")

        torepl = [x.group(0) for x in re.finditer(re_url, zz)]
        for s in range(len(torepl)):
            item = torepl[s]
            while item[-1] in typotools.PUNCTUATION:
                item = item[:-1]
            while (
                item[-1] in typotools.CLOSING_BRACKETS
                and typotools.find_matching_opening_bracket(item, -1) is None
            ):
                item = item[:-1]
            while item[-1] in typotools.PUNCTUATION:
                item = item[:-1]
            torepl[s] = item
        torepl = sorted(set(torepl), key=len, reverse=True)
        hashurls = {}
        for s in torepl:
            hashurls[s] = hashlib.md5(s.encode("utf8")).hexdigest()
        for s in sorted(hashurls, key=len, reverse=True):
            zz = zz.replace(s, hashurls[s])
        hashurls = {v: k for k, v in hashurls.items()}
        for s in sorted(hashurls):
            zz = zz.replace(s, "\\url{{{}}}".format(hashurls[s].replace("\\\\", "\\")))

        zz = zz.replace(" — ", "{\\Hair}—{\\hair}")

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
                        + "\u0301"
                        + zz[zz.index("`") + 2 :]
                    )
                elif zz.index("`") + 1 < len(zz) and re_uppercase.search(
                    zz[zz.index("`") + 1]
                ):
                    zz = (
                        zz[: zz.index("`") + 1]
                        + ""
                        + zz[zz.index("`") + 1]
                        + "\u0301"
                        + zz[zz.index("`") + 2 :]
                    )
                zz = zz[: zz.index("`")] + zz[zz.index("`") + 1 :]

        return zz

    def texformat(self, s):
        res = ""
        for run in self.parse_4s_elem(s):
            if run[0] == "":
                res += self.texrepl(run[1])
            if run[0] == "screen":
                res += self.texrepl(run[1]["for_print"])
            if run[0] == "italic":
                res += "\\emph{" + self.texrepl(run[1]) + "}"
            if run[0] == "img":
                parsed_image = parseimg(
                    run[1],
                    dimensions="ems",
                    tmp_dir=self.dir_kwargs.get("tmp_dir"),
                    targetdir=self.dir_kwargs.get("targetdir"),
                )
                imgfile = parsed_image["imgfile"]
                w = parsed_image["width"]
                h = parsed_image["height"]
                res += (
                    "\\includegraphics"
                    + "[width={}{}]".format(
                        "10em" if w == -1 else "{}em".format(w),
                        ", height={}em".format(h) if h != -1 else "",
                    )
                    + "{"
                    + imgfile
                    + "}"
                )
        while res.endswith("\n"):
            res = res[:-1]
        res = res.replace("\n", "  \\newline \n")
        return res

    def texyapper(self, e):
        if isinstance(e, str):
            return self.tex_element_layout(e)
        elif isinstance(e, list):
            if not any(isinstance(x, list) for x in e):
                return self.tex_element_layout(e)
            else:
                return "  \n".join([self.tex_element_layout(x) for x in e])

    def tex_element_layout(self, e):
        res = ""
        if isinstance(e, str):
            res = self.texformat(e)
            return res
        if isinstance(e, list):
            res = """
    \\begin{{compactenum}}
    {}
    \\end{{compactenum}}
    """.format("\n".join(["\\item {}".format(self.tex_element_layout(x)) for x in e]))
        return res

    def export(self, outfilename):
        self.qcount = 1
        tex = """\\input{@header}\n\\begin{document}""".replace(
            "@header", os.path.basename(self.args.tex_header)
        )
        firsttour = True
        for element in self.structure:
            if element[0] == "heading":
                tex += "\n{{\\huge {}}}\n\\vspace{{0.8em}}\n".format(
                    self.tex_element_layout(element[1])
                )
            if element[0] == "date":
                tex += "\n{{\\large {}}}\n\\vspace{{0.8em}}\n".format(
                    self.tex_element_layout(element[1])
                )
            if element[0] in {"meta", "editor"}:
                tex += "\n{}\n\\vspace{{0.8em}}\n".format(
                    self.tex_element_layout(element[1])
                )
            elif element[0] == "section":
                tex += "\n{}\\section*{{{}}}\n\n".format(
                    "\\clearpage" if not firsttour else "",
                    self.tex_element_layout(element[1]),
                )
                firsttour = False
            elif element[0] == "Question":
                tex += self.tex_format_question(element[1])

        tex += "\\end{document}"

        with codecs.open(outfilename, "w", "utf8") as outfile:
            outfile.write(tex)
        cwd = os.getcwd()
        os.chdir(self.dir_kwargs["tmp_dir"])
        subprocess.call(
            shlex.split(
                'xelatex -synctex=1 -interaction=nonstopmode "{}"'.format(outfilename)
            )
        )
        targetdir = os.path.dirname(outfilename)
        os.chdir(cwd)
        pdf_filename = os.path.splitext(os.path.basename(outfilename))[0] + ".pdf"
        self.logger.info("Output: {}".format(os.path.join(targetdir, pdf_filename)))
        shutil.copy(os.path.join(self.dir_kwargs["tmp_dir"], pdf_filename), targetdir)
        if self.args.rawtex:
            shutil.copy(outfilename, targetdir)
            shutil.copy(self.args.tex_header, targetdir)
            shutil.copy(
                os.path.join(self.dir_kwargs["tmp_dir"], "fix-unnumbered-sections.sty"),
                targetdir,
            )
