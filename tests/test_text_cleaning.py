from materials.text_cleaning import clean_pasted_text, clean_pdf_pages, word_count


def test_repeated_headers_and_page_numbers_are_removed():
    bodies = ["Atoms bond.", "Ions form salts.", "Acids donate protons.", "Bases accept them."]
    pages = [f"Chem 201 — Spring Term\n{body}\nPage {n} of 4" for n, body in enumerate(bodies, 1)]

    text = clean_pdf_pages(pages)

    assert "Chem 201" not in text
    assert "Page" not in text
    assert text.split("\n\n") == bodies


def test_headers_are_kept_when_there_are_too_few_pages_to_tell():
    text = clean_pdf_pages(["Intro to Law\nFirst page.", "Intro to Law\nSecond page."])

    assert text.count("Intro to Law") == 2


def test_bare_page_numbers_are_removed_even_on_short_documents():
    text = clean_pdf_pages(["Some text.\n1", "- 2 -\nMore text.", "iv\nRoman numerals."])

    assert text == "Some text.\n\nMore text.\n\nRoman numerals."


def test_wrapped_lines_are_joined_into_paragraphs():
    text = clean_pdf_pages(["Mitochondria are the\npowerhouse of the\ncell.\n\nNew paragraph."])

    assert text == "Mitochondria are the powerhouse of the cell.\n\nNew paragraph."


def test_words_hyphenated_across_lines_are_rejoined():
    text = clean_pdf_pages(["Plants perform photo-\nsynthesis in leaves."])

    assert text == "Plants perform photosynthesis in leaves."


def test_list_items_stay_on_their_own_lines():
    text = clean_pdf_pages(["Key terms:\n• Osmosis\n• Diffusion\n1. First step\n2) Second step"])

    assert text.split("\n\n") == [
        "Key terms:",
        "• Osmosis",
        "• Diffusion",
        "1. First step",
        "2) Second step",
    ]


def test_paragraph_split_by_a_page_break_is_rejoined():
    text = clean_pdf_pages(
        ["The enzyme binds to the\nsubstrate and", "lowers the activation energy."]
    )

    assert text == "The enzyme binds to the substrate and lowers the activation energy."


def test_ligatures_unmapped_glyphs_and_odd_spaces_are_normalised():
    text = clean_pdf_pages(["The ﬁrst ﬂow(cid:3) rate\tis   high."])

    assert text == "The first flow rate is high."


def test_pasted_text_keeps_line_breaks_and_tidies_whitespace():
    text = clean_pasted_text("  Heading\r\n\r\n\r\n\r\n- point one   \n- point two\t\n  ")

    assert text == "Heading\n\n- point one\n- point two"


def test_word_count():
    assert word_count("one two\nthree\n\nfour") == 4
    assert word_count("") == 0


def test_short_line_followed_by_a_capital_starts_a_new_paragraph():
    page = (
        "Cell Division\n"
        "Mitosis produces two identical daughter cells from a single parent\n"
        "cell and is used for growth and repair.\n"
        "Meiosis produces four genetically different gametes for reproduction."
    )

    assert clean_pdf_pages([page]).split("\n\n") == [
        "Cell Division",
        "Mitosis produces two identical daughter cells from a single parent "
        "cell and is used for growth and repair.",
        "Meiosis produces four genetically different gametes for reproduction.",
    ]
