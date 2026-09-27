import io

import pytest

from materials.extraction import ExtractionError, extract_pdf_text

from .pdfs import (
    GLOSSARY_DEFINITIONS,
    GLOSSARY_TABLE,
    GLOSSARY_TERMS,
    LECTURE,
    LEFT_COLUMN,
    RIGHT_COLUMN,
    TWO_COLUMNS,
    make_encrypted_pdf,
    make_pdf,
)


def test_extracts_and_cleans_multi_page_pdf():
    result = extract_pdf_text(io.BytesIO(make_pdf(LECTURE)))

    assert result.page_count == 3
    assert "Biology 101" not in result.text  # running header
    assert result.text.startswith("Photosynthesis\n\nPhotosynthesis converts light energy")
    assert "It takes place in the chloroplasts" in result.text
    assert "fix carbon dioxide into sugar." in result.text
    assert "\n3" not in result.text  # page number


def test_scanned_pdf_without_text_fails_with_a_helpful_message():
    with pytest.raises(ExtractionError, match="No text was found"):
        extract_pdf_text(io.BytesIO(make_pdf([None, None])))


def test_corrupt_pdf_fails():
    with pytest.raises(ExtractionError, match="couldn't be read"):
        extract_pdf_text(io.BytesIO(b"%PDF-1.4\nthis is not really a pdf"))


def test_truncated_pdf_fails():
    data = make_pdf(LECTURE)

    with pytest.raises(ExtractionError, match="couldn't be read"):
        extract_pdf_text(io.BytesIO(data[: len(data) // 3]))


def test_password_protected_pdf_fails():
    with pytest.raises(ExtractionError, match="password-protected"):
        extract_pdf_text(io.BytesIO(make_encrypted_pdf(LECTURE)))


def test_page_limit(settings):
    settings.MATERIAL_MAX_PDF_PAGES = 2

    with pytest.raises(ExtractionError, match="has 3 pages; the limit is 2"):
        extract_pdf_text(io.BytesIO(make_pdf(LECTURE)))


def test_two_column_pages_are_read_one_column_at_a_time():
    text = extract_pdf_text(io.BytesIO(make_pdf([TWO_COLUMNS]))).text

    title = "Enzymes and Reaction Rates: Week Three Overview"
    left = " ".join(LEFT_COLUMN)
    right = " ".join(RIGHT_COLUMN)
    assert text.index(title) < text.index(left) < text.index(right)


def test_words_are_separated_in_tightly_spaced_text():
    # Tc -1 squeezes the gaps between characters, as LaTeX output often does.
    pdf = make_pdf([[" Water moves across a membrane by osmosis."]]).replace(
        b"/F1 11 Tf", b"/F1 11 Tf -0.6 Tc"
    )

    text = extract_pdf_text(io.BytesIO(pdf)).text

    assert text == "Water moves across a membrane by osmosis."


def test_a_table_of_short_terms_is_not_mistaken_for_two_columns():
    text = extract_pdf_text(io.BytesIO(make_pdf([GLOSSARY_TABLE]))).text

    for term, definition in zip(GLOSSARY_TERMS, GLOSSARY_DEFINITIONS, strict=True):
        assert f"{term} {definition}" in text
