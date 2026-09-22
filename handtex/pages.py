"""Page extraction: render PDF pages to PNG and gather cheap local signals.

Notability's Google Drive backup flattens every page to a single raster
image, so a page's text layer (if any) only survives when the user hands us
the original LaTeX-generated PDF. We record what we can find locally and let
the vision model make the final call on raster pages.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# Claude reads images best when the long side is around 1500-1600 px.
TARGET_LONG_SIDE_PX = 1600
MIN_TEXT_CHARS = 40  # below this a "text layer" is just noise (page numbers, etc.)


@dataclass
class Page:
    number: int  # 1-based
    png: Path
    width_px: int
    height_px: int
    sha256: str
    text: str = ""  # extractable text layer, empty for raster pages
    has_text_layer: bool = False
    # Filled in later by the transcriber.
    kind: str | None = None  # typed | handwritten | mixed | blank
    latex: str = ""
    title: str = ""
    notes: list[str] = field(default_factory=list)


def render_pages(
    pdf_path: Path,
    out_dir: Path,
    pages: list[int] | None = None,
    long_side_px: int = TARGET_LONG_SIDE_PX,
) -> list[Page]:
    """Render each requested page to ``out_dir/page-NNN.png`` and return metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    wanted = pages or list(range(1, len(doc) + 1))
    result: list[Page] = []
    for number in wanted:
        if not 1 <= number <= len(doc):
            raise ValueError(f"page {number} out of range 1..{len(doc)}")
        page = doc[number - 1]
        long_side_pt = max(page.rect.width, page.rect.height)
        zoom = long_side_px / long_side_pt
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        png = out_dir / f"page-{number:03d}.png"
        pix.save(png)
        text = page.get_text().strip()
        result.append(
            Page(
                number=number,
                png=png,
                width_px=pix.width,
                height_px=pix.height,
                sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
                text=text,
                has_text_layer=len(text) >= MIN_TEXT_CHARS,
            )
        )
    doc.close()
    return result


def page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as doc:
        return len(doc)
