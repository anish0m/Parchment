from django.contrib import admin

from .models import ReviewLog, StudySession


@admin.register(StudySession)
class StudySessionAdmin(admin.ModelAdmin):
    list_display = ("course", "user", "started_at", "ended_at", "cards_reviewed", "cards_correct")
    list_filter = ("started_at",)
    search_fields = ("course__name", "user__username")
    list_select_related = ("course", "user")
    raw_id_fields = ("course", "user")


@admin.register(ReviewLog)
class ReviewLogAdmin(admin.ModelAdmin):
    list_display = ("flashcard", "user", "was_correct", "box_before", "box_after", "reviewed_at")
    list_filter = ("was_correct", "box_after", "reviewed_at")
    search_fields = ("flashcard__question", "user__username")
    list_select_related = ("flashcard", "user")
    raw_id_fields = ("flashcard", "user", "session")
