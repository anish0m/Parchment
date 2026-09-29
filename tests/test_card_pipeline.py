from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from flashcards.generation import pipeline
from flashcards.generation.generators import CardDraft, ClaudeGenerator, GenerationError
from flashcards.models import Flashcard
from materials.models import Material
from materials.services import create_material
from study.scheduler import record_answer

from .conftest import HTMX
from .sample_notes import NOTES


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def course(user, make_course):
    return make_course(user, "Science")


@pytest.fixture
def material(course):
    """A material processed end to end (sync tasks, TF-IDF, rules)."""
    return create_material(course, title="Week 1", source_type="text", text=NOTES)


def refreshed(material):
    material.refresh_from_db()
    return material


# --- Pipeline --------------------------------------------------------------------


def test_upload_generates_cards_grouped_by_concept(material):
    material = refreshed(material)
    cards = list(material.flashcards.all())

    assert material.status == "ready"
    assert "built-in rules" in material.generation_note
    assert len(cards) >= 5
    assert all(c.is_generated and c.course == material.course and c.box == 1 for c in cards)
    assert len({c.concept_label for c in cards}) >= 3
    assert all(c.concept_label and c.source_excerpt for c in cards)
    questions = [c.question for c in cards]
    assert "What is trench warfare?" in questions
    assert "What is plate tectonics?" in questions
    assert len(questions) == len(set(questions))


def test_card_limit_per_material(settings, course):
    settings.MAX_CARDS_PER_MATERIAL = 3

    material = create_material(course, title="Week 1", source_type="text", text=NOTES)

    assert material.flashcards.count() == 3


def test_short_material_is_ready_with_a_note(course):
    material = refreshed(create_material(course, title="Tiny", source_type="text", text="Hi."))

    assert material.status == "ready"
    assert "too short" in material.generation_note
    assert not material.flashcards.exists()


def test_regenerating_keeps_edited_studied_and_hand_added_cards(material):
    cards = list(material.flashcards.order_by("pk"))
    edited, studied = cards[0], cards[1]
    Flashcard.objects.filter(pk=edited.pk).update(question="My own wording?", is_edited=True)
    Flashcard.objects.filter(pk=studied.pk).update(box=3)
    by_hand = Flashcard.objects.create(
        course=material.course, material=material, question="Mine?", answer="Yes"
    )
    replaced = {c.pk for c in cards[2:]}

    pipeline.generate_flashcards(material)

    remaining = set(material.flashcards.values_list("pk", flat=True))
    assert {edited.pk, studied.pk, by_hand.pk} <= remaining
    assert not replaced & remaining  # the others were replaced by new cards
    # No new card duplicates the ones that were kept.
    studied_question = Flashcard.objects.get(pk=studied.pk).question
    assert material.flashcards.filter(question=studied_question).count() == 1


def test_regenerating_keeps_a_missed_card(material):
    """A card answered wrongly is back in box 1, but its review history must survive."""
    card = material.flashcards.first()
    record_answer(card, correct=False)
    assert card.box == 1

    pipeline.generate_flashcards(material)

    assert Flashcard.objects.filter(pk=card.pk).exists()
    assert card.reviews.count() == 1


def test_claude_is_used_when_configured(settings, material, monkeypatch):
    settings.CARD_GENERATOR = "claude"

    def fake_generate(self, concepts, title):
        return [
            CardDraft(f"Claude question {c.number}?", "Answer.", f"Concept {c.number}", "x")
            for c in concepts
        ]

    monkeypatch.setattr(ClaudeGenerator, "__init__", lambda self: setattr(self, "model", "m"))
    monkeypatch.setattr(ClaudeGenerator, "generate", fake_generate)

    result = pipeline.generate_flashcards(material)

    assert result.note == "Cards written by Claude (m)."
    assert material.flashcards.filter(question__startswith="Claude question").exists()


def test_claude_failure_falls_back_to_rules(settings, material, monkeypatch):
    settings.CARD_GENERATOR = "claude"

    def fail(self, concepts, title):
        raise GenerationError("the Anthropic API couldn't be reached")

    monkeypatch.setattr(ClaudeGenerator, "__init__", lambda self: setattr(self, "model", "m"))
    monkeypatch.setattr(ClaudeGenerator, "generate", fail)

    result = pipeline.generate_flashcards(material)

    assert result.note == (
        "Cards written by the built-in rules because the Anthropic API couldn't be reached."
    )
    assert result.created > 0


def test_unexpected_errors_fail_the_material_but_keep_its_text(course, monkeypatch):
    def boom(material):
        raise RuntimeError("bug")

    monkeypatch.setattr(pipeline, "generate_flashcards", boom)

    material = refreshed(create_material(course, title="W", source_type="text", text=NOTES))

    assert material.status == "failed"
    assert "Something went wrong" in material.error_message
    assert material.raw_text


def test_deleted_material_task_is_a_no_op(db):
    from materials.tasks import process_material, regenerate_cards

    process_material(999999)
    regenerate_cards(999999)


def test_tasks_are_queued_after_commit_when_not_sync(
    settings, course, monkeypatch, django_capture_on_commit_callbacks
):
    settings.Q_CLUSTER = {**settings.Q_CLUSTER, "sync": False}
    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **k: queued.append(a))

    with django_capture_on_commit_callbacks(execute=True):
        material = create_material(course, title="W", source_type="text", text=NOTES)
        assert queued == []  # nothing is sent until the transaction commits

    assert queued == [("materials.tasks.process_material", material.pk)]
    assert refreshed(material).status == "pending"


# --- Views -----------------------------------------------------------------------


def test_material_page_shows_cards_and_note(auth_client, material):
    content = auth_client.get(material.get_absolute_url()).content.decode()

    count = material.flashcards.count()
    assert f"{count} cards" in content
    assert f"?material={material.pk}" in content
    assert "built-in rules" in content
    assert "Regenerate cards" in content


def test_status_polling_while_in_progress(auth_client, material):
    Material.objects.filter(pk=material.pk).update(status="generating")
    url = reverse("materials:status", args=[material.pk])

    badge = auth_client.get(url, **HTMX)
    row = auth_client.get(url, {"view": "row"}, **HTMX)

    assert 'hx-trigger="every 2s"' in badge.content.decode()
    assert "HX-Refresh" not in badge
    assert "Generating cards" in row.content.decode()
    assert 'hx-trigger="every 3s"' in row.content.decode()


def test_status_reloads_the_page_when_finished(auth_client, material):
    response = auth_client.get(reverse("materials:status", args=[material.pk]), **HTMX)

    assert response["HX-Refresh"] == "true"
    assert "hx-trigger" not in response.content.decode()


def test_regenerate(auth_client, material):
    old = set(material.flashcards.values_list("pk", flat=True))

    response = auth_client.post(reverse("materials:regenerate", args=[material.pk]))

    assert response.status_code == 302
    assert refreshed(material).status == "ready"
    assert not old & set(material.flashcards.values_list("pk", flat=True))


def test_regenerate_is_refused_while_in_progress(auth_client, material):
    Material.objects.filter(pk=material.pk).update(status="generating")
    old = set(material.flashcards.values_list("pk", flat=True))

    auth_client.post(reverse("materials:regenerate", args=[material.pk]))

    assert set(material.flashcards.values_list("pk", flat=True)) == old


def test_stalled_material_can_be_retried(auth_client, material):
    long_ago = timezone.now() - timedelta(hours=2)
    Material.objects.filter(pk=material.pk).update(status="processing", updated_at=long_ago)

    page = auth_client.get(material.get_absolute_url(), follow=True).content.decode()
    auth_client.post(reverse("materials:regenerate", args=[material.pk]))

    assert "taking longer than expected" in page
    assert refreshed(material).status == "ready"


def test_failed_generation_offers_try_again(auth_client, material):
    Material.objects.filter(pk=material.pk).update(status="failed", error_message="Oops.")

    content = auth_client.get(material.get_absolute_url()).content.decode()

    assert "We couldn't generate flashcards" in content
    assert "Try again" in content
    assert "Extracted text" in content


@pytest.mark.parametrize("name, method", [("status", "get"), ("regenerate", "post")])
def test_other_users_cannot_see_or_regenerate(auth_client, other_user, make_course, name, method):
    theirs = create_material(
        make_course(other_user, "Theirs"), title="T", source_type="text", text=NOTES
    )

    response = getattr(auth_client, method)(reverse(f"materials:{name}", args=[theirs.pk]))

    assert response.status_code == 404


def test_editing_a_card_marks_it_edited(auth_client, material):
    card = material.flashcards.first()

    auth_client.post(
        reverse("flashcards:update", args=[card.pk]), {"question": "New?", "answer": "A"}
    )

    card.refresh_from_db()
    assert card.is_edited


def test_saving_an_unchanged_card_does_not_mark_it_edited(auth_client, material):
    card = material.flashcards.first()

    auth_client.post(
        reverse("flashcards:update", args=[card.pk]),
        {
            "question": card.question,
            "answer": card.answer,
            "concept_label": card.concept_label,
            "material": material.pk,
        },
    )

    card.refresh_from_db()
    assert not card.is_edited
