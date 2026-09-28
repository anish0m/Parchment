"""Splits cleaned text into overlapping chunks of a few sentences each."""

import re
from dataclasses import dataclass

TARGET_WORDS = 110
MAX_WORDS = 220
MIN_WORDS = 12
SHORT_NOTE_WORDS = 5  # when a material is one short note, keep chunks this long
OVERLAP_SENTENCES = 1

MAX_OVERLAP_WORDS = 40  # a longer sentence isn't repeated in the next chunk
PARAGRAPH_BREAK_SHARE = 0.6  # a chunk this full ends at the next paragraph break
HEADING_WORDS = 8

# A sentence ends at . ! or ? (maybe followed by a closing quote or bracket), then
# space and a capital, digit or opening mark.
SENTENCE_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))\s+(?=[\"'(\[]?[A-Z0-9•])")
# A heading that starts the back matter; everything after it is dropped.
BACK_MATTER = re.compile(r"^(\d+\.?\s*)?(references|bibliography|works cited)$", re.IGNORECASE)
CITATION = re.compile(r"\[\d+(?:[,–-]\s*\d+)*\]|\(\w[^()]{0,40}\d{4}[a-z]?\)|\bet al\.")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str

    @property
    def word_count(self):
        return len(self.text.split())


def split_sentences(paragraph):
    return [s.strip() for s in SENTENCE_END.split(paragraph) if s.strip()]


def _drop_back_matter(paragraphs):
    """Cuts a reference list off the end: a "References" heading in the second half."""
    for i, paragraph in enumerate(paragraphs):
        if i >= len(paragraphs) // 2 and BACK_MATTER.match(paragraph.strip()):
            return paragraphs[:i]
    return paragraphs


def _is_heading(paragraph):
    words = paragraph.split()
    return 0 < len(words) <= HEADING_WORDS and not paragraph.rstrip().endswith((".", "?", "!"))


def _sentences(text):
    """(sentence, starts_a_paragraph, is_a_heading) in order.

    Long run-on sentences are broken into windows of MAX_WORDS.
    """
    for paragraph in _drop_back_matter(text.split("\n\n")):
        paragraph = paragraph.replace("\n", " ").strip()
        heading = _is_heading(paragraph)
        if heading:
            paragraph += "."  # so it doesn't run into the next sentence in the chunk
        first = True
        for sentence in split_sentences(paragraph):
            words = sentence.split()
            for start in range(0, len(words), MAX_WORDS):
                yield " ".join(words[start : start + MAX_WORDS]), first, heading and first
                first = False


def _word_count(sentences):
    return sum(len(s.split()) for s in sentences)


def _is_useful(text, min_words=MIN_WORDS):
    words = text.split()
    if len(words) < min_words:
        return False
    letters = sum(ch.isalpha() for ch in text)
    if letters < 0.6 * len(text.replace(" ", "")):
        return False  # mostly numbers or symbols: tables, equations, page furniture
    return len(CITATION.findall(text)) < 3  # a block of references


def chunk_text(text):
    """Groups sentences into chunks of about TARGET_WORDS.

    Chunks end at headings, and at paragraph breaks once they're reasonably full,
    so a chunk rarely mixes two topics. Otherwise consecutive chunks overlap by a
    sentence, so an idea split across them keeps its context.
    """
    chunks, current, fresh = [], [], 0  # fresh: sentences in no chunk yet

    def flush(keep_overlap):
        nonlocal current, fresh
        if fresh:
            chunks.append(" ".join(current))
        tail = current[-OVERLAP_SENTENCES:] if keep_overlap and OVERLAP_SENTENCES else []
        current = [s for s in tail if len(s.split()) <= MAX_OVERLAP_WORDS]
        fresh = 0

    for sentence, new_paragraph, heading in _sentences(text):
        count = _word_count(current)
        if current and (
            heading or (new_paragraph and count >= PARAGRAPH_BREAK_SHARE * TARGET_WORDS)
        ):
            flush(keep_overlap=False)
        elif current and count + len(sentence.split()) > MAX_WORDS:
            flush(keep_overlap=True)
        current.append(sentence)
        fresh += 1
        if _word_count(current) >= TARGET_WORDS:
            flush(keep_overlap=True)
    flush(keep_overlap=False)

    useful = [chunk for chunk in chunks if _is_useful(chunk)]
    if not useful:
        # A short note is still worth a card or two.
        useful = [chunk for chunk in chunks if _is_useful(chunk, SHORT_NOTE_WORDS)]
    return [Chunk(index=i, text=chunk) for i, chunk in enumerate(useful)]
