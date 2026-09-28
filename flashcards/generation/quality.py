"""Drops weak and duplicate cards before they're saved."""

import re

MAX_QUESTION_CHARS = 400
MAX_ANSWER_CHARS = 700
DUPLICATE_SIMILARITY = 0.92


def _normalise(text):
    return re.sub(r"[^a-z0-9 ]", "", " ".join(text.lower().split()))


def is_acceptable(card):
    question, answer = _normalise(card.question), _normalise(card.answer)
    if not question or not answer:
        return False
    if len(card.question) > MAX_QUESTION_CHARS or len(card.answer) > MAX_ANSWER_CHARS:
        return False
    # An answer that just repeats the question teaches nothing.
    return answer != question and not (len(answer) > 20 and answer in question)


def filter_cards(drafts, embedder, existing_questions=()):
    """Acceptable cards, minus exact and near duplicates (of each other and of existing ones)."""
    drafts = [card for card in drafts if is_acceptable(card)]
    seen = {_normalise(q) for q in existing_questions}
    unique = []
    for card in drafts:
        key = _normalise(card.question)
        if key not in seen:
            seen.add(key)
            unique.append(card)
    if len(unique) < 2 and not existing_questions:
        return unique

    existing = list(existing_questions)
    vectors = embedder.encode(existing + [card.question for card in unique])
    if vectors.shape[1] == 0:
        return unique
    kept, kept_vectors = [], list(vectors[: len(existing)])
    for card, vector in zip(unique, vectors[len(existing) :], strict=True):
        if (
            kept_vectors
            and max(float(vector @ other) for other in kept_vectors) >= DUPLICATE_SIMILARITY
        ):
            continue
        kept.append(card)
        kept_vectors.append(vector)
    return kept
