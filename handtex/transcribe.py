"""Turn page images into LaTeX with Claude's vision, and repair what won't compile.

Each page is one request. The previous page's transcription rides along as
context so notation and section structure stay consistent across a note.
Results are cached on disk keyed by image hash + model + prompt version, so
re-running a note costs nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import anthropic

from .latex import PACKAGES, PREAMBLE, TIKZ_LIBRARIES
from .pages import Page
from .texcompile import check_fragment, pdflatex_available

DEFAULT_MODEL = "claude-opus-5"
PROMPT_VERSION = "1"
MAX_FIX_ROUNDS = 2

KINDS = ("typed", "handwritten", "mixed", "blank")

SYSTEM_PROMPT = f"""You transcribe scanned note pages into LaTeX.

Each page image comes from a note-taking app. A page is one of:
- "typed": typeset content only (a LaTeX article page, a beamer slide, a printed handout) with no handwriting on it.
- "handwritten": pen/pencil writing only, on ruled or blank paper.
- "mixed": typeset content with handwritten annotations on top or in the margins.
- "blank": nothing meaningful (empty, or only ruled lines / a page number).

Transcription rules:
- Transcribe only the handwriting. For "typed" pages return an empty string for latex; for "mixed" pages transcribe only the handwritten annotations, and say briefly (in prose) what part of the typed content each annotation refers to.
- Reproduce the author's content faithfully: the same statements, equations, proofs, examples and asides, in the same order. Do not add explanations, do not correct mathematics, do not omit things because they look like scratch work. If a word is illegible, write \\textbf{{[illegible]}} and add a note.
- Write structured LaTeX: use \\section*{{...}} / \\subsection*{{...}} for headings the author wrote; definition/theorem/lemma/proof environments where the author labelled them as such; align/align*/equation for displayed maths; itemize/enumerate for lists. Bra-ket notation uses the braket package (\\ket{{\\psi}}, \\bra{{\\phi}}, \\braket{{\\phi|\\psi}}).
- Diagrams and figures: redraw them in TikZ (or pgfplots for plotted curves) inside a figure or a centered tikzpicture. Aim for a clean schematic that carries the same information (labels, arrows, angles, shading), not pixel accuracy. Only fall back to \\textbf{{[diagram: ...]}} with a one-line description when a drawing genuinely cannot be represented.
- Output a body fragment only: no \\documentclass, no preamble, no \\begin{{document}}. It must compile as-is with this preamble, so use only these packages: {", ".join(PACKAGES)}; TikZ libraries loaded: {", ".join(TIKZ_LIBRARIES)}. Available theorem environments: definition, example, remark, theorem, lemma, proposition, corollary, claim; macros: \\R \\C \\N \\Z \\Q \\rank \\tr \\spn.
- Escape LaTeX specials in prose (%, &, #, _). Keep every \\begin matched with its \\end.
- Continuity: if the previous page's transcription is provided, continue it. Do not repeat a heading that is already open; if the page starts mid-sentence or mid-proof, continue without inventing a new section.

Respond with JSON only, matching the schema you are given: kind, title (a short title for the page, empty if none), latex (the body fragment), notes (a list of short strings: illegible spots, uncertain symbols, diagrams you could not draw)."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "title": {"type": "string"},
        "latex": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "title", "latex", "notes"],
    "additionalProperties": False,
}

FIX_PROMPT = """The LaTeX you produced for this page does not compile under the standard preamble. Here is the fragment:

<fragment>
{fragment}
</fragment>

pdflatex reported:

<error>
{error}
</error>

Return the corrected fragment for the same page (same kind and title; keep the content, fix the LaTeX). Respond with JSON only."""


@dataclass
class Transcript:
    kind: str
    title: str
    latex: str
    notes: list[str]
    model: str = ""
    fix_rounds: int = 0

    def to_json(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_json(cls, d: dict) -> "Transcript":
        return cls(**d)


class Transcriber(Protocol):
    def transcribe(self, page: Page, previous: Transcript | None) -> Transcript: ...

    def fix(self, page: Page, transcript: Transcript, error: str) -> Transcript: ...


class ClaudeTranscriber:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "high", client: anthropic.Anthropic | None = None):
        self.model = model
        self.effort = effort
        self.client = client or anthropic.Anthropic()

    # -- request plumbing ---------------------------------------------------

    def _image_block(self, page: Page) -> dict:
        data = base64.standard_b64encode(page.png.read_bytes()).decode("ascii")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}

    def _ask(self, content: list[dict]) -> Transcript:
        # Server-side refusal fallbacks are on by default; drop `fallbacks` and
        # the beta header if you would rather see refusals surface as errors.
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            why = getattr(details, "explanation", None) or "no explanation given"
            raise RuntimeError(f"model declined the page: {why}")
        if message.stop_reason == "max_tokens":
            raise RuntimeError("model output was cut off at max_tokens; try a smaller page range")
        text = next(b.text for b in message.content if b.type == "text")
        data = json.loads(text)
        return Transcript(
            kind=data["kind"],
            title=data["title"].strip(),
            latex=data["latex"].strip(),
            notes=[n for n in data["notes"] if n.strip()],
            model=message.model,
        )

    # -- public API ---------------------------------------------------------

    def transcribe(self, page: Page, previous: Transcript | None) -> Transcript:
        content: list[dict] = [self._image_block(page)]
        parts = [f"This is page {page.number}."]
        if page.has_text_layer:
            parts.append(
                "The page has a text layer (it was typeset), so it is 'typed' or 'mixed'. "
                "The extracted text follows so you can tell what is typeset:\n<typed_text>\n"
                + page.text[:6000]
                + "\n</typed_text>"
            )
        if previous and previous.latex:
            parts.append(
                "Transcription of the previous page, for continuity:\n<previous>\n" + previous.latex + "\n</previous>"
            )
        parts.append("Classify the page and transcribe the handwriting as described.")
        content.append({"type": "text", "text": "\n\n".join(parts)})
        return self._ask(content)

    def fix(self, page: Page, transcript: Transcript, error: str) -> Transcript:
        content = [
            self._image_block(page),
            {"type": "text", "text": FIX_PROMPT.format(fragment=transcript.latex, error=error)},
        ]
        fixed = self._ask(content)
        fixed.kind = transcript.kind
        fixed.title = fixed.title or transcript.title
        fixed.fix_rounds = transcript.fix_rounds + 1
        return fixed


# -- caching + validation -----------------------------------------------------


def _cache_key(page: Page, model: str) -> str:
    return hashlib.sha256(f"{page.sha256}|{model}|{PROMPT_VERSION}".encode()).hexdigest()[:24]


def transcribe_pages(
    pages: list[Page],
    transcriber: Transcriber,
    cache_dir: Path,
    model_tag: str,
    validate: bool = True,
    log=print,
) -> list[Page]:
    """Fill ``page.kind`` / ``page.latex`` for every page, using the cache when possible."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    previous: Transcript | None = None
    validate = validate and pdflatex_available()
    for page in pages:
        cache_file = cache_dir / f"{_cache_key(page, model_tag)}.json"
        if cache_file.exists():
            transcript = Transcript.from_json(json.loads(cache_file.read_text()))
            log(f"page {page.number}: cached ({transcript.kind})")
        else:
            log(f"page {page.number}: transcribing...")
            transcript = transcriber.transcribe(page, previous)
            if validate and transcript.latex:
                transcript = _repair(page, transcript, transcriber, cache_dir / "check", log)
            cache_file.write_text(json.dumps(transcript.to_json(), indent=2))
            log(f"page {page.number}: {transcript.kind}" + (f" - {transcript.title}" if transcript.title else ""))
        page.kind = transcript.kind
        page.title = transcript.title
        page.latex = transcript.latex
        page.notes = transcript.notes
        if transcript.latex:
            previous = transcript
    return pages


def _repair(page: Page, transcript: Transcript, transcriber: Transcriber, workdir: Path, log) -> Transcript:
    for attempt in range(MAX_FIX_ROUNDS + 1):
        result = check_fragment(transcript.latex, workdir, name=f"page-{page.number:03d}")
        if result.ok:
            return transcript
        if attempt == MAX_FIX_ROUNDS:
            log(f"page {page.number}: still not compiling after {MAX_FIX_ROUNDS} fixes; keeping it commented out")
            transcript.notes.append("LaTeX did not compile; fragment left commented out: " + result.error.splitlines()[0])
            transcript.latex = "\n".join("% " + line for line in transcript.latex.splitlines())
            return transcript
        log(f"page {page.number}: compile error, asking for a fix ({attempt + 1}/{MAX_FIX_ROUNDS})")
        transcript = transcriber.fix(page, transcript, result.error)
    return transcript
