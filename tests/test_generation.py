from types import SimpleNamespace

import numpy as np
import pytest

from flashcards.generation import embeddings
from flashcards.generation.chunking import MAX_WORDS, chunk_text, split_sentences
from flashcards.generation.clustering import build_concepts, choose_labels
from flashcards.generation.embeddings import TfidfEmbedder, get_embedder
from flashcards.generation.generators import (
    FALLBACK_BETA,
    CardDraft,
    ClaudeGenerator,
    ConceptInput,
    GeneratedCard,
    GeneratedConcept,
    GeneratedDeck,
    GenerationError,
    RuleBasedGenerator,
    get_generator,
)
from flashcards.generation.quality import filter_cards, is_acceptable

from .sample_notes import NOTES, PHOTOSYNTHESIS

# --- Chunking ------------------------------------------------------------------


def test_split_sentences():
    assert split_sentences("Cells divide. (Mostly!) Mitosis makes 2 cells? Yes.") == [
        "Cells divide.",
        "(Mostly!)",
        "Mitosis makes 2 cells?",
        "Yes.",
    ]


def test_chunks_group_sentences_and_overlap_by_one_within_a_paragraph():
    paragraph = " ".join(f"Sentence number {i} is about the topic of cells." for i in range(40))

    chunks = chunk_text(paragraph)

    assert len(chunks) >= 3
    assert all(c.word_count <= MAX_WORDS for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # Each chunk starts with the last sentence of the one before.
    last_sentence = split_sentences(chunks[0].text)[-1]
    assert chunks[1].text.startswith(last_sentence)


def test_chunks_break_at_headings_so_topics_dont_mix():
    chunks = chunk_text(NOTES)

    for chunk in chunks:
        topics = [
            name in chunk.text
            for name in ("chloroplast", "Treaty of Versailles", "Plate tectonics")
        ]
        assert sum(topics) <= 1
    assert chunks[0].text.startswith("Photosynthesis. Photosynthesis is")


def test_back_matter_is_dropped():
    text = PHOTOSYNTHESIS + "\n\nReferences\n\n" + "Smith, J. (2020). Plants and light. Nature."

    assert "Smith" not in " ".join(c.text for c in chunk_text(text))


def test_citation_heavy_chunks_are_dropped():
    refs = " ".join(f"Author {i} et al. wrote about leaves [{i}] (Jones 199{i})." for i in range(9))

    assert chunk_text(refs) == []


def test_a_short_note_still_makes_a_chunk():
    chunks = chunk_text("Osmosis moves water across membranes.")

    assert [c.text for c in chunks] == ["Osmosis moves water across membranes."]


def test_very_long_sentences_are_split():
    chunks = chunk_text(("word " * (MAX_WORDS * 2)).strip() + ".")

    assert chunks and all(c.word_count <= MAX_WORDS for c in chunks)


# --- Embeddings ------------------------------------------------------------------


def test_tfidf_vectors_are_normalised_and_similar_texts_are_close():
    vectors = TfidfEmbedder().encode(
        ["plants use light in chloroplasts", "chloroplasts capture light", "the treaty of 1919"]
    )

    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
    assert vectors[0] @ vectors[1] > vectors[0] @ vectors[2]


def test_auto_embedder_falls_back_to_tfidf_and_remembers(settings, monkeypatch):
    settings.EMBEDDING_BACKEND = "auto"
    settings.EMBEDDING_MODEL = "missing/model"
    calls = []

    def fail(name):
        calls.append(name)
        raise OSError("no network")

    monkeypatch.setattr(embeddings, "_load_sentence_transformer", fail)
    monkeypatch.setattr(embeddings, "_unavailable", set())

    assert isinstance(get_embedder(), TfidfEmbedder)
    assert isinstance(get_embedder(), TfidfEmbedder)
    assert calls == ["missing/model"]  # not retried


def test_forced_sentence_transformers_does_not_fall_back(settings, monkeypatch):
    settings.EMBEDDING_BACKEND = "sentence-transformers"
    monkeypatch.setattr(
        embeddings, "_load_sentence_transformer", lambda name: (_ for _ in ()).throw(OSError())
    )

    with pytest.raises(OSError):
        get_embedder()


# --- Clustering ----------------------------------------------------------------


def concepts_for(text, max_clusters=12):
    texts = [c.text for c in chunk_text(text)]
    vectors = TfidfEmbedder().encode(texts)
    return texts, build_concepts(vectors, choose_labels(vectors, max_clusters), texts)


def test_distinct_topics_become_separate_concepts_in_document_order():
    texts, concepts = concepts_for(NOTES)

    assert 3 <= len(concepts) <= 6
    assert [c.first_index for c in concepts] == sorted(c.first_index for c in concepts)
    topic_of = {}
    for n, concept in enumerate(concepts):
        for i in concept.chunk_indices:
            topic_of[i] = n
    # Chunks from different topics don't share a concept.
    first = topic_of[0]
    last = topic_of[len(texts) - 1]
    assert first != last
    keywords = " ".join(k for c in concepts for k in c.keywords)
    assert any(word in keywords for word in ("photosynthesis", "chloroplast", "light"))
    assert any(word in keywords for word in ("plate", "boundaries", "earthquake"))


def test_few_chunks_make_one_concept():
    _, concepts = concepts_for(PHOTOSYNTHESIS.split("\n\n")[1])

    assert len(concepts) == 1


def test_max_clusters_is_respected():
    _, concepts = concepts_for(NOTES, max_clusters=2)

    assert len(concepts) <= 2


def test_representatives_are_members_in_order():
    _, concepts = concepts_for(NOTES)

    for concept in concepts:
        assert set(concept.representative_indices) <= set(concept.chunk_indices)
        assert concept.representative_indices == sorted(concept.representative_indices)
        assert 1 <= len(concept.representative_indices) <= 4


# --- Rule-based generator --------------------------------------------------------


def rule_cards(*excerpts, keywords=("photosynthesis",)):
    concept = ConceptInput(number=1, excerpts=list(excerpts), keywords=list(keywords))
    return RuleBasedGenerator().generate([concept])


def test_definitions_become_what_is_cards():
    cards = rule_cards("Trench warfare is a type of fighting where armies dig trenches.")

    assert cards[0].question == "What is trench warfare?"
    assert cards[0].answer == "A type of fighting where armies dig trenches."
    assert cards[0].source_excerpt.startswith("Trench warfare is")


def test_proper_nouns_and_acronyms_keep_their_capitals():
    cards = rule_cards(
        "Rubisco fixes carbon onto sugars in the stroma of every leaf.",
        "ATP is the molecule that stores and moves energy within cells.",
        keywords=["rubisco"],
    )

    assert cards[0].question == "What is ATP?"


@pytest.mark.parametrize(
    "sentence",
    [
        "The first step is to collect the leaves carefully.",
        "This is a process that plants use every single day.",
        "Related work is discussed in Section 8 of the paper.",
        "The remainder of this paper is organized as follows.",
        "As long as m is small, the trees are easy to handle.",
    ],
)
def test_vague_or_non_definitions_are_skipped(sentence):
    cards = rule_cards(sentence, keywords=[])

    assert cards == []


def test_key_terms_become_fill_in_the_blank_cards():
    cards = rule_cards(
        "Plants absorb light with chlorophyll inside their chloroplasts every day.",
        keywords=["chlorophyll"],
    )

    assert cards[0].question == (
        "Fill in the blank: Plants absorb light with _____ inside their chloroplasts every day."
    )
    assert cards[0].answer == "Chlorophyll."


def test_concept_label_uses_the_notes_casing():
    cards = RuleBasedGenerator().generate(
        [
            ConceptInput(
                1,
                ["The FFI is the interface that lets the interpreter call C code."],
                ["ffi"],
            )
        ]
    )

    assert cards[0].concept_label == "FFI"


# --- Claude generator ------------------------------------------------------------


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response, self.error = response, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


CONCEPTS = [
    ConceptInput(1, ["Chlorophyll absorbs red and blue light."], ["chlorophyll"]),
    ConceptInput(2, ["The treaty was signed in 1919."], ["treaty"]),
]


def deck_response(*concepts, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=GeneratedDeck(concepts=concepts))


def test_claude_generator_request_and_cards(settings):
    settings.MAX_CARDS_PER_CONCEPT = 2
    client = FakeClient(
        deck_response(
            GeneratedConcept(
                concept_number=1,
                concept_name="  Light   absorption ",
                cards=[
                    GeneratedCard(
                        question="Which colours does chlorophyll absorb?",
                        answer="Red and blue light.",
                        source_quote="Chlorophyll absorbs red and blue light.",
                    ),
                    GeneratedCard(
                        question="Q2?", answer="A2", source_quote="Not from the notes at all."
                    ),
                    GeneratedCard(question="Q3?", answer="A3", source_quote=""),
                ],
            ),
            GeneratedConcept(concept_number=99, concept_name="Made up", cards=[]),
        )
    )

    cards = ClaudeGenerator(client=client, model="claude-opus-5", effort="medium").generate(
        CONCEPTS, "Week 1"
    )

    call = client.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["betas"] == [FALLBACK_BETA]
    assert call["fallbacks"] == "default"
    assert call["output_format"] is GeneratedDeck
    assert call["output_config"] == {"effort": "medium"}
    prompt = call["messages"][0]["content"]
    assert "Material: Week 1" in prompt
    assert '<concept number="2">' in prompt
    assert "Chlorophyll absorbs red and blue light." in prompt

    assert len(cards) == 2  # capped per concept; unknown concept skipped
    assert cards[0] == CardDraft(
        question="Which colours does chlorophyll absorb?",
        answer="Red and blue light.",
        concept_label="Light absorption",
        source_excerpt="Chlorophyll absorbs red and blue light.",
    )
    # A quote that isn't in the notes is replaced with the concept's excerpt.
    assert cards[1].source_excerpt == "Chlorophyll absorbs red and blue light."


@pytest.mark.parametrize(
    "response, message",
    [
        (deck_response(stop_reason="refusal"), "declined"),
        (deck_response(stop_reason="max_tokens"), "cut off"),
        (SimpleNamespace(stop_reason="end_turn", parsed_output=None), "couldn't be read"),
    ],
)
def test_claude_generator_unusable_responses(response, message):
    with pytest.raises(GenerationError, match=message):
        ClaudeGenerator(client=FakeClient(response)).generate(CONCEPTS)


def test_claude_generator_connection_error():
    import anthropic
    import httpx2

    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://example.com"))

    with pytest.raises(GenerationError, match="couldn't be reached"):
        ClaudeGenerator(client=FakeClient(error=error)).generate(CONCEPTS)


def test_generator_choice(settings, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    settings.CARD_GENERATOR = "auto"
    assert isinstance(get_generator(), RuleBasedGenerator)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(get_generator(), ClaudeGenerator)

    settings.CARD_GENERATOR = "rules"
    assert isinstance(get_generator(), RuleBasedGenerator)


# --- Quality filters -------------------------------------------------------------


def draft(question, answer="An answer."):
    return CardDraft(question=question, answer=answer, concept_label="", source_excerpt="")


@pytest.mark.parametrize(
    "card, ok",
    [
        (draft("What is osmosis?", "Water moving across a membrane."), True),
        (draft("", "Answer"), False),
        (draft("What is osmosis?", "   "), False),
        (draft("What is osmosis?", "What is osmosis"), False),
        (
            draft(
                "What moves water across a membrane by osmosis?",
                "water across a membrane by osmosis",
            ),
            False,
        ),
        (draft("Q" * 401), False),
    ],
)
def test_acceptable_cards(card, ok):
    assert is_acceptable(card) is ok


def test_duplicates_are_removed():
    cards = [
        draft("What is osmosis?"),
        draft("what is OSMOSIS?"),
        draft("What is trench warfare?"),
        draft("What is plate tectonics?"),
    ]

    kept = filter_cards(cards, TfidfEmbedder(), existing_questions=["What is plate tectonics?"])

    assert [c.question for c in kept] == ["What is osmosis?", "What is trench warfare?"]


def test_long_documents_get_more_concepts():
    def topic(i):
        facts = " ".join(f"Fact {j} about subject{i} uses term{i}x{j % 3}." for j in range(80))
        return f"Topic {i}\n\n{facts}"

    _, concepts = concepts_for("\n\n".join(topic(i) for i in range(8)), max_clusters=12)

    assert len(concepts) >= 5  # about 40 chunks, aiming for ~7 concepts
