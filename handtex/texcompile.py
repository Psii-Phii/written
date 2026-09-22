"""Run pdflatex and pull the first real error out of the log."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .latex import PREAMBLE


@dataclass
class CompileResult:
    ok: bool
    pdf: Path | None
    error: str  # trimmed excerpt of the log around the first error, "" when ok


def pdflatex_available() -> bool:
    return shutil.which("pdflatex") is not None


def compile_tex(tex_path: Path, runs: int = 2) -> CompileResult:
    """Compile ``tex_path`` in place; run twice so references settle."""
    if not pdflatex_available():
        return CompileResult(False, None, "pdflatex not found on PATH")
    workdir = tex_path.parent
    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        tex_path.name,
    ]
    for _ in range(runs):
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
        if proc.returncode != 0:
            log = workdir / tex_path.with_suffix(".log").name
            text = log.read_text(errors="replace") if log.exists() else proc.stdout
            return CompileResult(False, None, extract_error(text))
    pdf = tex_path.with_suffix(".pdf")
    return CompileResult(pdf.exists(), pdf if pdf.exists() else None, "")


_ERROR_RE = re.compile(r"^(?:! |.*:\d+: )", re.MULTILINE)


def extract_error(log: str, context_lines: int = 12) -> str:
    """Return the first error line plus a little context; the whole log is noise."""
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if _ERROR_RE.match(line):
            return "\n".join(lines[i : i + context_lines])
    return "\n".join(lines[-context_lines:])


def check_fragment(fragment: str, workdir: Path, name: str = "fragment") -> CompileResult:
    """Compile a body fragment on its own under the standard preamble."""
    workdir.mkdir(parents=True, exist_ok=True)
    tex = workdir / f"{name}.tex"
    tex.write_text(PREAMBLE + "\\begin{document}\n" + fragment + "\n\\end{document}\n")
    return compile_tex(tex, runs=1)
