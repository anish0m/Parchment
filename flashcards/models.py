from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from courses.models import Course
from materials.models import Material

# Leitner boxes run from 1 (reviewed most often) to LEITNER_BOXES (mastered).
LEITNER_BOXES = 5


class Flashcard(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="flashcards")
    # Cards outlive their material: deleting notes shouldn't wipe study progress.
    material = models.ForeignKey(
        Material,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="flashcards",
    )
    question = models.TextField()
    answer = models.TextField()
    concept_label = models.CharField("concept", max_length=120, blank=True)
    source_excerpt = models.TextField(blank=True)
    box = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(LEITNER_BOXES)]
    )
    # New cards are due straight away.
    next_review_at = models.DateTimeField(default=timezone.now)
    is_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["concept_label", "created_at", "pk"]
        indexes = [
            models.Index(fields=["course", "next_review_at"]),
            models.Index(fields=["course", "box"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(box__gte=1, box__lte=LEITNER_BOXES),
                name="flashcard_box_in_range",
            ),
        ]

    def __str__(self):
        return self.question[:80]
