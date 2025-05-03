HEADER = r"""
\documentclass{minimal}
\usepackage[paperwidth=<PAPERWIDTH>mm,paperheight=<PAPERHEIGHT>mm,top=<MARGIN_TOP>mm,bottom=<MARGIN_BOTTOM>mm,left=<MARGIN_LEFT>mm,right=<MARGIN_RIGHT>mm]{geometry}
\frenchspacing
\usepackage{fontspec}
\usepackage{xcolor}
\usepackage{tikz}
\usepackage{calc}
\usepackage[document]{ragged2e}
\setmainfont{Arial}
\newlength{\boxwidth}
\newlength{\boxwidthinner}
\begin{document}
\fontsize{14pt}{16pt}\selectfont
\setlength\parindent{0pt}
\tikzstyle{box}=[draw, dashed, rectangle, inner sep=<TIKZ_MM>mm]
\raggedright
\raggedbottom
""".strip()

GREYTEXT = r"""{\fontsize{9pt}{11pt}\selectfont \textcolor{gray}{<GREYTEXT>}}"""

GREYTEXT_LANGS = {
    "by": "Да пытаньня {}",
    "en": "Handout for question {}",
    "kz": "{}-сұрақтың үлестіру материалы",
    "ro": "Material care urmează a fi distribuit pentru întrebarea {}",
    "ru": "К вопросу {}",
    "sr": "Materijal za deljenje uz pitanje {}",
    "ua": "До запитання {}",
    "uz": "{} саволга тарқатма материал",
}

TIKZBOX_START = r"""{<CENTERING>
"""

TIKZBOX_INNER = r"""
\begin{tikzpicture}
\node[box, minimum width=\boxwidth<TEXTWIDTH><ALIGN>] {<FONTSIZE><CONTENTS>\par};
\end{tikzpicture}
""".strip()

TIKZBOX_END = "\n}"

IMG = r"""\includegraphics<IMGWIDTH>{<IMGPATH>}"""

IMGWIDTH = r"[width=<QWIDTH>\textwidth]"
