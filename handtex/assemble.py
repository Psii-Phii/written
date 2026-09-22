"""Build the output .tex from classified pages.

Two shapes come out of this:

* notes mode - every page is handwriting, so the result is a standalone
  article made of the transcriptions.
* presentation mode - some pages are typeset (slides, a LaTeX handout), so
  those pages are kept as-is with pdfpages and the handwriting is typeset
  in between, right where it was in the note.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .latex import PREAMBLE
from .pages import Page


def tex_escape(s: str) -> str:
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    return s


def choose_mode(pages: list[Page]) -> str:
    return "presentation" if any(p.kind in ("typed", "mixed") for p in pages) else "notes"


def _notes_block(page: Page) -> str:
    if not page.notes:
        return ""
    items = "\n".join(f"  \\item {tex_escape(n)}" for n in page.notes)
    return f"\\begin{{itemize}}[nosep]\n{items}\n\\end{{itemize}}\n"


def build_document(
    pages: list[Page],
    title: str,
    source_pdf: Path | None,
    out_dir: Path,
    original_pdf: Path | None = None,
) -> str:
    """Return the full .tex text.

    ``source_pdf`` is the note PDF (typed pages are pulled from it by page
    number). ``original_pdf`` is an optional crisp copy of the presentation;
    when given, the k-th typed page in the note is taken from page k of it.
    """
    mode = choose_mode(pages)
    # Note files are called things like "Note Jan 24, 2024.pdf"; spaces and
    # commas break \includepdf, so typed pages are pulled from a safely named copy.
    if mode == "presentation":
        if original_pdf is not None:
            shutil.copyfile(original_pdf, out_dir / "original.pdf")
        else:
            shutil.copyfile(source_pdf, out_dir / "source.pdf")
    body: list[str] = []
    body.append(f"\\title{{{tex_escape(title)}}}\n\\date{{}}\n\\author{{}}")
    body.append("\\begin{document}")
    if mode == "notes":
        body.append("\\maketitle")

    typed_seen = 0
    for page in pages:
        if page.kind == "blank":
            continue
        if page.kind in ("typed", "mixed"):
            typed_seen += 1
            src, num = ("original.pdf", typed_seen) if original_pdf is not None else ("source.pdf", page.number)
            body.append(f"% page {page.number}: {page.kind}")
            body.append(f"\\includepdf[pages={num}, pagecommand={{}}]{{{src}}}")
            if page.kind == "mixed" and page.latex:
                heading = page.title or f"Annotations on page {page.number}"
                body.append(f"\\section*{{{tex_escape(heading)}}}")
                body.append(page.latex)
                body.append(_notes_block(page))
                body.append("\\clearpage")
            continue
        # handwritten
        body.append(f"% page {page.number}: handwritten" + (f" - {page.title}" if page.title else ""))
        body.append(page.latex)
        body.append(_notes_block(page))
        if mode == "presentation":
            body.append("\\clearpage")
        else:
            body.append("")

    body.append("\\end{document}")
    return PREAMBLE + "\n" + "\n".join(body) + "\n"
