"""End-to-end checks that need no API key: render, assemble, compile.

The stub transcriber returns a hand-written transcription of a real page
(quantum fidelity notes with a unit-circle TikZ diagram) so the compile path
is exercised with realistic LaTeX.
"""

from pathlib import Path

import pymupdf
import pytest

from handtex.assemble import build_document, choose_mode
from handtex.pages import render_pages
from handtex.texcompile import check_fragment, compile_tex, pdflatex_available
from handtex.transcribe import Transcript, transcribe_pages

FIDELITY_PAGE = r"""
$\ket{\psi}$, $\ket{\phi}$ are distinguishable $\iff$ $\ket{\psi}$ and $\ket{\phi}$ are orthogonal.

By exercise from last time we can perfectly distinguish between $\ket{0}$ \& $\ket{1}$ or $\ket{+}$ and $\ket{-}$.

More generally any two states in the same ON basis. But not between e.g.\ $\ket{0}$, $\ket{+}$ or $\ket{1}$ and $\ket{-}$.

\subsection*{Fidelity}
Given state $\ket{\phi}$ in a quantum register and state $\ket{\psi}$ we would like to ``measure'' distance
\[ \| \ket{\phi} - \ket{\psi} \|, \]
however, cannot directly observe $\ket{\phi}$. Instead, we can look for a kind of substitute.

Complex unit circle / torus:
\begin{center}
\begin{tikzpicture}[scale=1.2]
  \draw[thick] (0,0) circle (1);
  \draw[->] (0,0) -- (0.94,0.34);
  \draw[->] (0,0) -- (0.5,0.87) node[above right] {$\eta$};
  \draw (0.4,0) arc (0:60:0.4) node[midway, right] {$\theta$};
\end{tikzpicture}
\end{center}
Can tell apart by $\theta$.
"""

MATRIX_PAGE = r"""
\begin{theorem}
A PSD matrix with rank $r$ can be written as the sum of at most $r$ rank-1 PSD matrices.
\end{theorem}
\begin{proof}
We go by induction on $\rank(A)$. Choose $x \in \R^n$ s.t.\ $Ax \neq 0$; if no such $x$ exists then $A = 0$ and we are done. Otherwise define
\[ B = A - \frac{1}{x^T A x} A x x^T A . \]
\end{proof}
"""


class StubTranscriber:
    """Returns canned transcripts; records what it was asked for."""

    def __init__(self, kinds: dict[int, str]):
        self.kinds = kinds
        self.calls: list[int] = []

    def transcribe(self, page, previous):
        self.calls.append(page.number)
        kind = self.kinds.get(page.number, "handwritten")
        latex = "" if kind in ("typed", "blank") else (FIDELITY_PAGE if page.number == 1 else MATRIX_PAGE)
        return Transcript(kind=kind, title=f"Page {page.number}", latex=latex, notes=[])

    def fix(self, page, transcript, error):
        raise AssertionError("fix should not be needed for the canned fragments")


@pytest.fixture
def note_pdf(tmp_path: Path) -> Path:
    """A three-page PDF: a typeset page, then two blank-ish raster pages."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Lecture 4: Fidelity of quantum states. " * 5, fontsize=11)
    for y in (100, 140):  # distinct raster pages, no text layer
        page = doc.new_page()
        page.draw_line((30, y), (500, y))
    path = tmp_path / "Note Jan 24, 2024.pdf"
    doc.save(path)
    return path


def test_render_detects_text_layer(note_pdf, tmp_path):
    pages = render_pages(note_pdf, tmp_path / "pages")
    assert [p.number for p in pages] == [1, 2, 3]
    assert pages[0].has_text_layer and not pages[1].has_text_layer
    assert all(p.png.exists() for p in pages)
    assert max(pages[0].width_px, pages[0].height_px) == 1600


def test_cache_skips_second_run(note_pdf, tmp_path):
    pages = render_pages(note_pdf, tmp_path / "pages")
    stub = StubTranscriber({1: "typed"})
    transcribe_pages(pages, stub, tmp_path / "cache", model_tag="stub", validate=False)
    transcribe_pages(pages, stub, tmp_path / "cache", model_tag="stub", validate=False)
    assert stub.calls == [1, 2, 3]  # second run served entirely from cache
    assert [p.kind for p in pages] == ["typed", "handwritten", "handwritten"]


@pytest.mark.skipif(not pdflatex_available(), reason="pdflatex not installed")
def test_fragments_compile(tmp_path):
    assert check_fragment(FIDELITY_PAGE, tmp_path, "a").ok
    assert check_fragment(MATRIX_PAGE, tmp_path, "b").ok
    bad = check_fragment(r"\begin{align} x &= 1", tmp_path, "c")
    assert not bad.ok and bad.error


@pytest.mark.skipif(not pdflatex_available(), reason="pdflatex not installed")
@pytest.mark.parametrize("kinds,mode", [({1: "typed"}, "presentation"), ({1: "handwritten"}, "notes")])
def test_document_compiles(note_pdf, tmp_path, kinds, mode):
    out = tmp_path / "out"
    out.mkdir()
    pages = render_pages(note_pdf, out / "pages")
    transcribe_pages(pages, StubTranscriber(kinds), out / "cache", model_tag="stub", validate=False)
    assert choose_mode(pages) == mode
    tex = build_document(pages, "Fidelity", source_pdf=note_pdf, out_dir=out)
    tex_path = out / "notes.tex"
    tex_path.write_text(tex)
    result = compile_tex(tex_path)
    assert result.ok, result.error
    with pymupdf.open(result.pdf) as pdf:
        text = "".join(p.get_text() for p in pdf)
        assert len(pdf) >= (3 if mode == "presentation" else 1)
    assert "Fidelity" in text and "PSD matrix" in text
    if mode == "presentation":
        assert r"\includepdf[pages=1" in tex
        assert "Lecture 4" in text  # the typed page was carried over intact
