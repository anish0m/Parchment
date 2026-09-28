"""Numbers for the end-of-session summary and the course progress page."""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, F, Max, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from flashcards.models import LEITNER_BOXES

from .models import ReviewLog

RECENT_SESSIONS = 10


def _percent(part, whole):
    return round(100 * part / whole) if whole else None


@dataclass
class SessionSummary:
    reviewed: int
    correct: int
    promoted: int
    demoted: int
    due_now: int
    next_due: object  # datetime or None

    @property
    def missed(self):
        return self.reviewed - self.correct

    @property
    def accuracy(self):
        return _percent(self.correct, self.reviewed)


def session_summary(session, now=None):
    now = now or timezone.now()
    moves = session.reviews.aggregate(
        promoted=Count("pk", filter=Q(box_after__gt=F("box_before"))),
        demoted=Count("pk", filter=Q(box_after__lt=F("box_before"))),
    )
    cards = session.course.flashcards
    return SessionSummary(
        reviewed=session.cards_reviewed,
        correct=session.cards_correct,
        promoted=moves["promoted"],
        demoted=moves["demoted"],
        due_now=cards.filter(next_review_at__lte=now).count(),
        next_due=cards.filter(next_review_at__gt=now).aggregate(at=Min("next_review_at"))["at"],
    )


@dataclass
class BoxRow:
    box: int
    count: int
    interval_days: int
    share: int  # percent of all cards
    width: int  # bar length, percent of the fullest box


@dataclass
class SessionRow:
    session: object
    accuracy: int


def study_streak(dates, today):
    """Days in a row with at least one review, ending today (or yesterday, if not yet today)."""
    dates = set(dates)
    day = today if today in dates else today - timedelta(days=1)
    streak = 0
    while day in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def course_progress(course, now=None):
    now = now or timezone.now()
    cards = course.flashcards
    by_box = dict(cards.values_list("box").annotate(n=Count("pk")).order_by())
    total = sum(by_box.values())
    fullest = max(by_box.values(), default=0)
    boxes = [
        BoxRow(
            box=box,
            count=by_box.get(box, 0),
            interval_days=settings.LEITNER_INTERVAL_DAYS[box - 1],
            share=_percent(by_box.get(box, 0), total) or 0,
            width=_percent(by_box.get(box, 0), fullest) or 0,
        )
        for box in range(1, LEITNER_BOXES + 1)
    ]

    reviews = ReviewLog.objects.filter(flashcard__course=course)
    totals = reviews.aggregate(
        count=Count("pk"), correct=Count("pk", filter=Q(was_correct=True)), last=Max("reviewed_at")
    )
    days = reviews.annotate(day=TruncDate("reviewed_at", tzinfo=timezone.get_current_timezone()))
    streak = study_streak(days.values_list("day", flat=True).distinct(), timezone.localdate(now))

    recent = list(
        course.study_sessions.filter(cards_reviewed__gt=0).order_by("-started_at", "-pk")[
            :RECENT_SESSIONS
        ]
    )
    sessions = [
        SessionRow(session=s, accuracy=_percent(s.cards_correct, s.cards_reviewed)) for s in recent
    ]

    return {
        "card_count": total,
        "boxes": boxes,
        "mastered": by_box.get(LEITNER_BOXES, 0),
        "due_now": cards.filter(next_review_at__lte=now).count(),
        "next_due": cards.filter(next_review_at__gt=now).aggregate(at=Min("next_review_at"))["at"],
        "review_count": totals["count"],
        "accuracy": _percent(totals["correct"], totals["count"]),
        "last_studied": totals["last"],
        "streak": streak,
        "sessions": sessions,
    }
