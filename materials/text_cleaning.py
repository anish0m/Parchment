"""Turns raw text (per PDF page, or pasted) into clean text for flashcard generation."""

import re
from collections import Counter

LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)

# "12", "Page 12", "page 3 of 10", "3 / 10", "- 12 -", "xii"
PAGE_NUMBER = re.compile(
    r"^[\s\-–—]*(page\s+)?(\d+|[ivxlcdm]+)(\s*(of|/)\s*\d+)?[\s\-–—]*$", re.IGNORECASE
)
# Lines that start a new item and so shouldn't be merged into the previous line.
LIST_ITEM = re.compile(r"^(\s*([•●▪◦○■□\-–*]|\(?\d{1,3}[.)]|\(?[a-z][.)])\s)")
SENTENCE_END = re.compile(r"[.!?:;]['\")\]]?$")

# How many lines at the top and bottom of a page can be a running header or footer.
EDGE_LINES = 2


def _signature(line):
    """Normalises a line so headers/footers match across pages even when a number changes."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip().lower()))


def _repeated_edge_lines(pages):
    """Signatures of lines that repeat at the top/bottom of many pages."""
    if len(pages) < 3:
        return set()
    counts = Counter()
    for lines in pages:
        edges = {_signature(line) for line in lines[:EDGE_LINES] + lines[-EDGE_LINES:]}
        counts.update(sig for sig in edges if sig)
    threshold = max(3, len(pages) // 2)
    return {sig for sig, count in counts.items() if count >= threshold}


def _strip_page_furniture(lines, repeated):
    """Drops running headers/footers and page numbers from the edges of one page."""
    lines = list(lines)
    for edge in ("top", "bottom"):
        for _ in range(EDGE_LINES):
            if not lines:
                break
            line = lines[0] if edge == "top" else lines[-1]
            if _signature(line) in repeated or PAGE_NUMBER.match(line) or not line.strip():
                lines.pop(0 if edge == "top" else -1)
            else:
                break
    return lines


def _normalise(text):
    text = text.translate(LIGATURES)
    text = re.sub(r"\(cid:\d+\)", "", text)  # glyphs pdfminer couldn't map
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t  -   　]", " ", text)
    text = re.sub(r"[​­﻿]", "", text)  # zero-width and soft hyphens
    return text


def _typical_line_length(lines):
    lengths = sorted(len(line.strip()) for line in lines if line.strip())
    return lengths[int(0.75 * (len(lengths) - 1))] if lengths else 0


def _join_wrapped_lines(lines):
    """Rebuilds paragraphs from PDF lines that were wrapped at the page margin.

    PDF text has no blank lines between paragraphs, so a line that stops well
    short of the margin (a heading, or a paragraph's last line) followed by a
    capitalised line starts a new paragraph.
    """
    short = 0.6 * _typical_line_length(lines)
    paragraphs, current, previous = [], "", ""
    for line in lines:
        line = line.strip()
        if not line:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        if not current:
            current = line
        elif LIST_ITEM.match(line) or (len(previous) < short and line[:1].isupper()):
            paragraphs.append(current)
            current = line
        elif re.search(r"[a-z]-$", current) and line[:1].islower():
            # A word hyphenated across lines: "photo-" + "synthesis".
            current = current[:-1] + line
        else:
            current = f"{current} {line}"
        previous = line
    if current:
        paragraphs.append(current)
    return paragraphs


def _tidy(text):
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_pdf_pages(pages):
    """Cleans the text of each PDF page and joins them into one document."""
    split = [_normalise(page or "").split("\n") for page in pages]
    repeated = _repeated_edge_lines(split)
    paragraphs = []
    for lines in split:
        paragraphs.extend(_join_wrapped_lines(_strip_page_furniture(lines, repeated)))
    # A paragraph cut by a page break continues on the next page.
    merged = []
    for paragraph in paragraphs:
        if (
            merged
            and not SENTENCE_END.search(merged[-1])
            and paragraph[:1].islower()
            and not LIST_ITEM.match(paragraph)
        ):
            merged[-1] = f"{merged[-1]} {paragraph}"
        else:
            merged.append(paragraph)
    return _tidy("\n\n".join(merged))


def clean_pasted_text(text):
    """Pasted text keeps the user's own line breaks; only whitespace is tidied."""
    return _tidy(_normalise(text))


def word_count(text):
    return len(text.split())
