from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from courses.models import Course
from flashcards.models import LEITNER_BOXES, Flashcard

BOX_IN_RANGE = {"gte": 1, "lte": LEITNER_BOXES}


class StudySession(models.Model):
    """One sitting of reviews in a course; the counts are kept up to date as answers come in."""

    class Mode(models.TextChoices):
        DUE = "due", "Due cards"
        # "Study anyway": nothing is due, so review the cards coming due soonest.
        PRACTICE = "practice", "Extra practice"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="study_sessions"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="study_sessions")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.DUE)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    cards_reviewed = models.PositiveIntegerField(default=0)
    cards_correct = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at", "-pk"]
        indexes = [models.Index(fields=["course", "started_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cards_correct__lte=models.F("cards_reviewed")),
                name="session_correct_within_reviewed",
            ),
        ]

    def __str__(self):
        return f"{self.course} · {self.started_at:%Y-%m-%d %H:%M}"

    def get_absolute_url(self):
        return reverse("study:session", args=[self.pk])

    @property
    def is_active(self):
        return self.ended_at is None

    @property
    def accuracy(self):
        """Share of answers that were correct, from 0 to 1, or None before any answer."""
        return self.cards_correct / self.cards_reviewed if self.cards_reviewed else None


class ReviewLog(models.Model):
    """One answer to one card, and the box move it caused."""

    flashcard = models.ForeignKey(Flashcard, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    session = models.ForeignKey(
        StudySession, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviews"
    )
    was_correct = models.BooleanField()
    box_before = models.PositiveSmallIntegerField()
    box_after = models.PositiveSmallIntegerField()
    reviewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-reviewed_at", "-pk"]
        indexes = [
            models.Index(fields=["flashcard", "reviewed_at"]),
            models.Index(fields=["user", "reviewed_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(**{f"box_before__{k}": v for k, v in BOX_IN_RANGE.items()}),
                name="review_box_before_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(**{f"box_after__{k}": v for k, v in BOX_IN_RANGE.items()}),
                name="review_box_after_in_range",
            ),
        ]

    def __str__(self):
        verdict = "correct" if self.was_correct else "missed"
        return f"{self.flashcard} · {verdict} · box {self.box_before} → {self.box_after}"

    @property
    def was_promoted(self):
        return self.box_after > self.box_before

    @property
    def was_demoted(self):
        return self.box_after < self.box_before
