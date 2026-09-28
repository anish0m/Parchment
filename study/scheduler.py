"""Leitner scheduling: moves cards between boxes and decides when they're due.

A correct answer moves a card up one box (staying in the top box once there); a
wrong one sends it back to box 1. The card is then due again after its new box's
interval (settings.LEITNER_INTERVAL_DAYS), counted from the start of the day it
was answered, so "due tomorrow" means from midnight rather than at the same minute.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from flashcards.models import LEITNER_BOXES, Flashcard

from .models import ReviewLog, StudySession


class SessionError(ValueError):
    """The session can't take this answer (another course, or already ended)."""


def interval_for(box):
    """How long a card waits in `box` before it's due again."""
    if not 1 <= box <= LEITNER_BOXES:
        raise ValueError(f"Box must be between 1 and {LEITNER_BOXES}, not {box}.")
    return timedelta(days=settings.LEITNER_INTERVAL_DAYS[box - 1])


def next_box(box, correct):
    return min(box + 1, LEITNER_BOXES) if correct else 1


def next_review_time(box, now=None):
    """When a card placed in `box` at `now` is next due: midnight, `interval` days on."""
    now = now or timezone.now()
    day = timezone.localtime(now).date() + interval_for(box)
    return timezone.make_aware(datetime.combine(day, time.min))


def record_answer(card, correct, *, session=None, now=None):
    """Apply one answer to `card`: move its box, reschedule it and log the review.

    Everything happens in one transaction, with the card's row locked so two quick
    submissions of the same answer can't both apply to the old box. `card` is
    updated in place. Returns the ReviewLog.
    """
    now = now or timezone.now()
    with transaction.atomic():
        locked = (
            Flashcard.objects.select_for_update(of=("self",))
            .select_related("course")
            .get(pk=card.pk)
        )
        if session is not None:
            session = StudySession.objects.select_for_update().get(pk=session.pk)
            if session.course_id != locked.course_id:
                raise SessionError("This card belongs to a different course than the session.")
            if not session.is_active:
                raise SessionError("This study session has already ended.")

        box_before = locked.box
        locked.box = next_box(box_before, correct)
        locked.next_review_at = next_review_time(locked.box, now)
        locked.save(update_fields=["box", "next_review_at", "updated_at"])

        log = ReviewLog.objects.create(
            flashcard=locked,
            user=locked.course.owner,
            session=session,
            was_correct=correct,
            box_before=box_before,
            box_after=locked.box,
            reviewed_at=now,
        )
        if session is not None:
            StudySession.objects.filter(pk=session.pk).update(
                cards_reviewed=F("cards_reviewed") + 1,
                cards_correct=F("cards_correct") + int(bool(correct)),
            )

    card.box, card.next_review_at, card.updated_at = (
        locked.box,
        locked.next_review_at,
        locked.updated_at,
    )
    return log


def due_cards(course, limit=None, now=None):
    """Cards in `course` due by `now`: lowest box first, then the longest overdue.

    New cards are due as soon as they're made, so they're included.
    """
    now = now or timezone.now()
    cards = course.flashcards.filter(next_review_at__lte=now).order_by(
        "box", "next_review_at", "pk"
    )
    return cards[:limit] if limit is not None else cards


def start_session(course, now=None):
    return StudySession.objects.create(
        user=course.owner, course=course, started_at=now or timezone.now()
    )


def end_session(session, now=None):
    """Mark `session` as finished; ending it twice keeps the first end time."""
    if session.ended_at is None:
        session.ended_at = now or timezone.now()
        session.save(update_fields=["ended_at"])
    return session
