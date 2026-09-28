import uuid

from django.db import models
from django.urls import reverse

from courses.models import Course


def material_upload_to(instance, filename):
    # Random names: the user's filename is kept in original_filename, never used as a path.
    return f"materials/{instance.course_id}/{uuid.uuid4().hex}.pdf"


class Material(models.Model):
    class SourceType(models.TextChoices):
        TEXT = "text", "Pasted text"
        PDF = "pdf", "PDF"

    class Status(models.TextChoices):
        PENDING = "pending", "Queued"
        PROCESSING = "processing", "Reading text"
        GENERATING = "generating", "Generating cards"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    IN_PROGRESS = (Status.PENDING, Status.PROCESSING, Status.GENERATING)

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="materials")
    title = models.CharField(max_length=200)
    source_type = models.CharField(max_length=10, choices=SourceType.choices)
    file = models.FileField(upload_to=material_upload_to, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    raw_text = models.TextField(blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    word_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True)
    # How the latest cards were made, e.g. which generator and why.
    generation_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["course", "-created_at"])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("materials:detail", args=[self.pk])

    @property
    def is_pdf(self):
        return self.source_type == self.SourceType.PDF

    @property
    def in_progress(self):
        return self.status in self.IN_PROGRESS
