"""handtex: turn a note PDF (typed pages + handwriting) into a LaTeX document.

    handtex "Note Jan 24, 2024.pdf"
    handtex slides-annotated.pdf --original slides.pdf --title "Lecture 4"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .assemble import build_document, choose_mode
from .pages import render_pages
from .texcompile import compile_tex, pdflatex_available
from .transcribe import DEFAULT_MODEL, ClaudeTranscriber, transcribe_pages


def parse_pages(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="handtex", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="the note PDF (e.g. a Notability export)")
    ap.add_argument("-o", "--out", type=Path, help="output directory (default: <pdf name>_tex next to the PDF)")
    ap.add_argument("--title", help="document title (default: the PDF's file name)")
    ap.add_argument("--original", type=Path, help="the original typeset PDF (slides/handout); typed pages are taken from it instead of the note's raster copy")
    ap.add_argument("--pages", help="only these pages, e.g. 1-3,7")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--no-compile", action="store_true", help="write the .tex but do not run pdflatex")
    ap.add_argument("--no-cache", action="store_true", help="ignore cached transcriptions")
    args = ap.parse_args(argv)

    pdf: Path = args.pdf.resolve()
    if not pdf.exists():
        print(f"error: {pdf} does not exist", file=sys.stderr)
        return 2
    out_dir: Path = (args.out or pdf.with_name(pdf.stem.replace(" ", "_") + "_tex")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    title = args.title or pdf.stem
    if args.no_cache and (out_dir / "cache").exists():
        shutil.rmtree(out_dir / "cache")

    print(f"rendering {pdf.name} -> {out_dir}/pages")
    pages = render_pages(pdf, out_dir / "pages", parse_pages(args.pages))

    transcriber = ClaudeTranscriber(model=args.model, effort=args.effort)
    pages = transcribe_pages(pages, transcriber, out_dir / "cache", model_tag=args.model)

    mode = choose_mode(pages)
    tex = build_document(pages, title, source_pdf=pdf, out_dir=out_dir, original_pdf=args.original.resolve() if args.original else None)
    tex_path = out_dir / "notes.tex"
    tex_path.write_text(tex)
    (out_dir / "pages.json").write_text(json.dumps(
        [{"page": p.number, "kind": p.kind, "title": p.title, "notes": p.notes} for p in pages], indent=2))
    print(f"mode: {mode}; wrote {tex_path}")

    flagged = [(p.number, n) for p in pages for n in p.notes]
    if flagged:
        print("things to check by hand:")
        for number, note in flagged:
            print(f"  page {number}: {note}")

    if args.no_compile:
        return 0
    if not pdflatex_available():
        print("pdflatex not found; skipping compile (install TeX Live or use --no-compile)")
        return 0
    result = compile_tex(tex_path)
    if result.ok:
        print(f"compiled {result.pdf}")
        return 0
    print("compile failed:\n" + result.error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
