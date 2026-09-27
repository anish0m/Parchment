"""Pulls text out of uploaded materials."""

import logging
from dataclasses import dataclass
from statistics import median

import pdfplumber
from django.conf import settings
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from .text_cleaning import clean_pdf_pages

logger = logging.getLogger(__name__)

# Fewer letters than this across the whole PDF means there is no real text layer.
MIN_TEXT_CHARS = 20

# Gaps wider than 15% of the font size count as spaces. pdfplumber's default (a
# fixed 3pt) glues words together in tightly set PDFs such as LaTeX papers.
TEXT_OPTIONS = {"x_tolerance_ratio": 0.15}

# Two-column detection: the gutter is searched for in the middle of the page.
GUTTER_SEARCH = (0.3, 0.7)  # fraction of page width
GUTTER_STEP = 2  # points
MIN_GUTTER_GAP = 0.02  # fraction of page width; a word space is much narrower
MIN_WORDS_FOR_COLUMNS = 40
MIN_COLUMN_SHARE = 0.2  # each column holds at least this share of the words
# Typical line width in each column, as a fraction of the page width. Text columns
# are wide; a table of short terms beside long definitions is not two columns.
MIN_COLUMN_WIDTH = 0.25
MAX_SPANNING_LINES = 0.35  # share of lines allowed to run across the gutter (titles)
MAX_SPANNING_DEPTH = 0.4  # full-width content must sit in the top 40% of the page


class ExtractionError(Exception):
    """A problem with the file that the user can act on; the message is shown to them."""


@dataclass
class ExtractedText:
    text: str
    page_count: int


def extract_pdf_text(fileobj):
    try:
        with pdfplumber.open(fileobj) as pdf:
            page_count = len(pdf.pages)
            if page_count > settings.MATERIAL_MAX_PDF_PAGES:
                raise ExtractionError(
                    f"This PDF has {page_count} pages; the limit is "
                    f"{settings.MATERIAL_MAX_PDF_PAGES}. Split it into smaller files."
                )
            pages = []
            for page in pdf.pages:
                pages.append(_page_text(page))
                page.close()  # free each page's parsed objects as we go
    except PdfminerException as exc:
        cause = exc.args[0] if exc.args else None
        if isinstance(cause, PDFPasswordIncorrect | PDFEncryptionError):
            raise ExtractionError(
                "This PDF is password-protected. Remove the password and upload it again."
            ) from exc
        raise ExtractionError("This file couldn't be read as a PDF. It may be damaged.") from exc
    except ExtractionError:
        raise
    except Exception as exc:
        logger.exception("Unexpected error reading PDF")
        raise ExtractionError("This file couldn't be read as a PDF. It may be damaged.") from exc

    text = clean_pdf_pages(pages)
    if sum(ch.isalpha() for ch in text) < MIN_TEXT_CHARS:
        raise ExtractionError(
            "No text was found in this PDF. It looks like a scanned document or images "
            "of pages, which isn't supported yet. Paste the text instead, or upload a PDF "
            "with selectable text."
        )
    return ExtractedText(text=text, page_count=page_count)


def _group_lines(words, tolerance=3):
    """Groups words into text lines by their vertical position."""
    lines = []
    for word in sorted(words, key=lambda w: w["top"]):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _extent(words):
    return max(w["x1"] for w in words) - min(w["x0"] for w in words)


def _find_gutter(page, words):
    """Finds the x position between two text columns, or None for a single column.

    Returns (x, spanning_words). A line counts as spanning (like a title above the
    columns) when a word crosses x or the gap at x is no wider than a word space.
    """
    if len(words) < MIN_WORDS_FOR_COLUMNS:
        return None
    lines = _group_lines(words)
    x0, _, x1, _ = page.bbox
    width = x1 - x0
    min_gap = width * MIN_GUTTER_GAP
    best = None
    x = x0 + width * GUTTER_SEARCH[0]
    while x <= x0 + width * GUTTER_SEARCH[1]:
        spanning, left, right, left_widths, right_widths = [], 0, 0, [], []
        for line in lines:
            line_left = [w for w in line if w["x1"] <= x]
            line_right = [w for w in line if w["x0"] >= x]
            crosses = len(line_left) + len(line_right) < len(line)
            narrow = (
                line_left
                and line_right
                and min(w["x0"] for w in line_right) - max(w["x1"] for w in line_left) < min_gap
            )
            if crosses or narrow:
                spanning.append(line)
            else:
                left += len(line_left)
                right += len(line_right)
                if line_left:
                    left_widths.append(_extent(line_left))
                if line_right:
                    right_widths.append(_extent(line_right))
        if (
            min(left, right) >= MIN_COLUMN_SHARE * len(words)
            and len(spanning) <= MAX_SPANNING_LINES * len(lines)
            and min(median(left_widths), median(right_widths)) >= MIN_COLUMN_WIDTH * width
        ):
            # Prefer the fewest spanning lines, then the gutter nearest the centre.
            score = (len(spanning), abs(x - (x0 + width / 2)))
            if best is None or score < best[0]:
                best = (score, x, [w for line in spanning for w in line])
        x += GUTTER_STEP
    return best[1:] if best else None


def _page_text(page):
    """Extracts a page's text, reading two-column layouts one column at a time."""
    words = page.extract_words(**TEXT_OPTIONS)
    gutter = _find_gutter(page, words)
    if gutter is None:
        return page.extract_text(**TEXT_OPTIONS) or ""

    x, spanning = gutter
    x0, y0, x1, y1 = page.bbox
    top = max((w["bottom"] for w in spanning), default=y0)
    if top > y0 + (y1 - y0) * MAX_SPANNING_DEPTH:
        # Full-width content (a wide figure or table) low on the page: splitting
        # would cut it in half, so read the page as a whole.
        return page.extract_text(**TEXT_OPTIONS) or ""

    regions = [(x0, top, x, y1), (x, top, x1, y1)]
    if spanning:
        regions.insert(0, (x0, y0, x1, top))  # the title block above the columns
    # within_bbox (not crop) so a word on a boundary lands in one region, not both.
    parts = (page.within_bbox(bbox).extract_text(**TEXT_OPTIONS) for bbox in regions)
    return "\n\n".join(part for part in parts if part)
