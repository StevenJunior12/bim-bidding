"""Structured document parsing: detect headings and preserve hierarchy."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Section:
    heading_level: int  # 0 = body text, 1/2/3 = heading depth
    heading_text: str
    content: str  # body text under this heading (excluding the heading itself)
    children: list[Section] = field(default_factory=list)


def parse_document_structured(file_path: str | Path) -> list[Section]:
    """Parse a document into structured sections with heading levels.

    Returns a flat list of Section objects ordered by appearance.
    heading_level=0 means unclassified body text before any heading.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf_structured(path)
    if suffix == ".docx":
        return _parse_docx_structured(path)
    raise ValueError(f"Unsupported file type: {suffix}; use .pdf or .docx")


# ---------------------------------------------------------------------------
# DOCX: use paragraph styles for heading detection
# ---------------------------------------------------------------------------

_HEADING_STYLE_RE = re.compile(r"^heading\s*(\d+)", re.IGNORECASE)
_HEADING_STYLE_CN_RE = re.compile(r"^标题\s*(\d+)")


def _detect_docx_heading_level(paragraph) -> int:
    """Return heading level (1-6) or 0 for normal paragraphs."""
    style_name = paragraph.style.name if paragraph.style else ""
    m = _HEADING_STYLE_RE.match(style_name)
    if not m:
        m = _HEADING_STYLE_CN_RE.match(style_name)
    if m:
        return min(int(m.group(1)), 6)

    # Fallback: outline level in XML
    pPr = paragraph._element.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}outlineLvl")
    if pPr is not None:
        val = pPr.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
        if val is not None:
            try:
                return min(int(val) + 1, 6)
            except (ValueError, TypeError):
                pass
    return 0


def _parse_docx_structured(path: Path) -> list[Section]:
    from docx import Document

    doc = Document(path)
    sections: list[Section] = []
    current: Section | None = None

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        level = _detect_docx_heading_level(para)
        if level > 0:
            current = Section(heading_level=level, heading_text=text, content="")
            sections.append(current)
        else:
            if current is not None:
                current.content += ("\n" if current.content else "") + text
            else:
                # Body text before any heading
                sections.append(Section(heading_level=0, heading_text="", content=text))

    return sections


# ---------------------------------------------------------------------------
# PDF: use font-size heuristics + regex patterns for heading detection
# ---------------------------------------------------------------------------

# Common bidding document heading patterns
_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千\d]+[章节部分]")
_SECTION_RE = re.compile(r"^(\d+)\s*[.、．]")
_SUBSECTION_RE = re.compile(r"^(\d+\.[\d]+)")


def _detect_pdf_heading(text: str, font_size: float, body_size: float, is_bold: bool) -> int:
    """Return heading level (1-3) or 0 for body text."""
    # Regex-based detection (high confidence)
    if _CHAPTER_RE.match(text):
        return 1
    if _SUBSECTION_RE.match(text):
        return 3
    if _SECTION_RE.match(text):
        return 2

    # Font-size heuristic: significantly larger than body text
    if body_size <= 0:
        return 0
    ratio = font_size / body_size
    if ratio >= 1.5 and is_bold:
        return 1
    if ratio >= 1.3 and is_bold:
        return 2
    if ratio >= 1.15 and is_bold:
        return 3
    return 0


def _estimate_body_font_size(path: Path) -> float:
    """Estimate the most common (body) font size in the document."""
    import fitz

    doc = fitz.open(path)
    size_counts: dict[float, int] = {}
    try:
        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block["type"] != 0:  # text blocks only
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = round(span["size"], 1)
                        size_counts[size] = size_counts.get(size, 0) + len(span["text"])
    finally:
        doc.close()

    if not size_counts:
        return 0.0
    return max(size_counts, key=lambda size: size_counts[size])


def _parse_pdf_structured(path: Path) -> list[Section]:
    import fitz

    body_size = _estimate_body_font_size(path)

    doc = fitz.open(path)
    sections: list[Section] = []
    current: Section | None = None

    try:
        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block.get("lines", []):
                    line_text = ""
                    line_size = 0.0
                    line_bold = False
                    for span in line.get("spans", []):
                        line_text += span["text"]
                        line_size = max(line_size, span["size"])
                        if "bold" in (span.get("font") or "").lower():
                            line_bold = True

                    text = line_text.strip()
                    if not text:
                        continue

                    level = _detect_pdf_heading(text, line_size, body_size, line_bold)
                    if level > 0:
                        current = Section(heading_level=level, heading_text=text, content="")
                        sections.append(current)
                    else:
                        if current is not None:
                            current.content += ("\n" if current.content else "") + text
                        else:
                            sections.append(Section(heading_level=0, heading_text="", content=text))
    finally:
        doc.close()

    return sections
