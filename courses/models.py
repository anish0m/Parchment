from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse


class Course(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="courses"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint("owner", Lower("name"), name="unique_course_name_per_owner"),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("courses:detail", args=[self.pk])
