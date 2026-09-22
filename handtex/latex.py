"""The fixed LaTeX preamble shared by the transcriber prompt and the assembler.

Keeping one preamble in one place means the model is told exactly which
packages exist, and the assembled document really has them.
"""

PACKAGES = [
    "amsmath",
    "amssymb",
    "amsthm",
    "mathtools",
    "braket",
    "enumitem",
    "graphicx",
    "tikz",
    "pgfplots",
    "pdfpages",
    "hyperref",
]

TIKZ_LIBRARIES = [
    "arrows.meta",
    "calc",
    "positioning",
    "shapes.geometric",
    "decorations.pathmorphing",
    "decorations.pathreplacing",
    "matrix",
    "patterns",
]

PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
""" + "\n".join(rf"\usepackage{{{p}}}" for p in PACKAGES) + r"""
\usetikzlibrary{""" + ",".join(TIKZ_LIBRARIES) + r"""}
\pgfplotsset{compat=1.18}
\hypersetup{colorlinks=true, linkcolor=blue!50!black, urlcolor=blue!50!black}

\theoremstyle{definition}
\newtheorem{definition}{Definition}[section]
\newtheorem{example}[definition]{Example}
\newtheorem{remark}[definition]{Remark}
\theoremstyle{plain}
\newtheorem{theorem}[definition]{Theorem}
\newtheorem{lemma}[definition]{Lemma}
\newtheorem{proposition}[definition]{Proposition}
\newtheorem{corollary}[definition]{Corollary}
\newtheorem{claim}[definition]{Claim}

\newcommand{\R}{\mathbb{R}}
\newcommand{\C}{\mathbb{C}}
\newcommand{\N}{\mathbb{N}}
\newcommand{\Z}{\mathbb{Z}}
\newcommand{\Q}{\mathbb{Q}}
\DeclareMathOperator{\rank}{rank}
\DeclareMathOperator{\tr}{tr}
\DeclareMathOperator{\spn}{span}
"""
