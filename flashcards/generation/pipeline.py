"""Runs a material's text through every stage and saves the resulting cards."""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from flashcards.models import Flashcard

from .chunking import chunk_text
from .clustering import build_concepts, choose_labels
from .embeddings import get_embedder
from .generators import (
    ClaudeGenerator,
    ConceptInput,
    GeminiGenerator,
    GenerationError,
    RuleBasedGenerator,
    get_generator,
)
from .quality import filter_cards

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Cards can't be made; the message is shown to the user."""


@dataclass
class PipelineResult:
    created: int
    note: str


def replaceable_cards(material):
    """Generated cards that regenerating may replace: never edited, never studied."""
    return material.flashcards.filter(is_generated=True, is_edited=False, box=1)


def _generate(concepts, title):
    generator = get_generator()
    if isinstance(generator, (GeminiGenerator, ClaudeGenerator)):
        try:
            drafts = generator.generate(concepts, title)
            return drafts, f"Cards written by {generator.label} ({generator.model})."
        except GenerationError as exc:
            logger.warning("%s generation failed, using rules: %s", generator.label, exc)
            reason = f"because {exc}"
    elif settings.CARD_GENERATOR == "rules":
        reason = ""
    else:
        reason = "because no Gemini or Anthropic API key is set"
    drafts = RuleBasedGenerator().generate(concepts, title)
    return drafts, " ".join(f"Cards written by the built-in rules {reason}".split()) + "."


def generate_flashcards(material):
    chunks = chunk_text(material.raw_text)
    if not chunks:
        return PipelineResult(
            created=0,
            note="This material is too short to make flashcards from; you can add cards by hand.",
        )
    texts = [chunk.text for chunk in chunks]

    embedder = get_embedder()
    vectors = embedder.encode(texts)
    labels = choose_labels(vectors, settings.MAX_CONCEPTS_PER_MATERIAL)
    concepts = [
        ConceptInput(
            number=n,
            excerpts=[texts[i] for i in concept.representative_indices],
            keywords=concept.keywords,
        )
        for n, concept in enumerate(build_concepts(vectors, labels, texts), start=1)
    ]
    drafts, note = _generate(concepts, material.title)

    with transaction.atomic():
        replaced = list(replaceable_cards(material).values_list("pk", flat=True))
        existing = material.course.flashcards.exclude(pk__in=replaced).values_list(
            "question", flat=True
        )
        cards = filter_cards(drafts, embedder, list(existing))[: settings.MAX_CARDS_PER_MATERIAL]
        Flashcard.objects.filter(pk__in=replaced).delete()
        Flashcard.objects.bulk_create(
            Flashcard(
                course=material.course,
                material=material,
                question=card.question,
                answer=card.answer,
                concept_label=card.concept_label[:120],
                source_excerpt=card.source_excerpt,
                is_generated=True,
            )
            for card in cards
        )

    if not cards:
        note += " No new cards could be made from this material; you can add cards by hand."
    logger.info("Generated %d cards for material %s (%s)", len(cards), material.pk, embedder.name)
    return PipelineResult(created=len(cards), note=note)
