# handtex

Turn a note PDF from Notability (or any other note app) into LaTeX:

- **Handwritten pages** are transcribed into real LaTeX: headings, theorem and
  proof environments, aligned equations, bra-ket notation, lists. Diagrams are
  redrawn in TikZ (curves in pgfplots).
- **Typeset pages** (a beamer deck or a LaTeX handout you annotated) are kept
  exactly as they are, and the handwritten pages are typeset in between them,
  where they sat in the note.

So a beamer presentation with handwritten notes becomes `presentation + tex
notes` in one document, and a purely handwritten note becomes a full LaTeX
article.

## Setup

```sh
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...     # transcription runs on Claude's vision
```

`pdflatex` (TeX Live with `tikz`, `pgfplots`, `pdfpages`, `braket`) is needed to
compile; without it handtex still writes the `.tex`.

## Use

```sh
handtex "Note Jan 24, 2024.pdf"
handtex "Lecture 4 annotated.pdf" --original lecture4.pdf --title "Lecture 4"
handtex big-note.pdf --pages 1-5      # try a few pages first
```

Output goes to `<note name>_tex/`:

| file | what |
|---|---|
| `notes.tex`, `notes.pdf` | the result |
| `pages/page-NNN.png` | the rendered pages sent to the model |
| `pages.json` | per-page classification, titles, and things to check by hand |
| `cache/` | transcriptions keyed by image hash; re-runs are free |

Things the model was unsure about (illegible words, a diagram it could not
draw) are printed at the end of the run and left in the document as
`[illegible]` / `[diagram: ...]` markers.

### `--original`

Notability's Google Drive backup flattens every page to an image, so slides
in a note come back as rasters. Pass the original presentation PDF with
`--original` and the k-th typeset page of the note is taken from page k of it,
so the slides stay crisp and searchable.

## How it works

1. `pages.py` renders each page to a ~1600 px PNG and notes whether it has a
   text layer.
2. `transcribe.py` sends each page to Claude with a fixed system prompt and a
   JSON schema (`kind`, `title`, `latex`, `notes`). The previous page's
   transcription is included so notation and sections stay consistent. Each
   fragment is compiled on its own under the standard preamble; if it fails,
   the error is sent back and the model fixes it (two rounds, then the
   fragment is left commented out and flagged).
3. `assemble.py` writes the document: `\includepdf` for typed pages, the
   transcriptions for handwritten ones. `latex.py` holds the one preamble
   both the prompt and the document use.
4. `texcompile.py` runs `pdflatex` twice.

`--model` and `--effort` pick the model (default `claude-opus-5`, effort
`high`). Server-side refusal fallbacks are enabled.

## Getting notes out of Notability

Notability → Settings → Auto-Backup → Google Drive, format PDF. The `Notability`
folder then appears in Drive (Google Drive for desktop syncs it locally), and
each note is `Note <date>.pdf`. Or share a single note as PDF.

## Tests

```sh
pip install pytest
pytest
```

The tests use a stub transcriber and need no API key; the compile tests are
skipped when `pdflatex` is missing.
