from django.contrib import admin

from .models import Flashcard


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = (
        "question_preview",
        "course",
        "concept_label",
        "box",
        "next_review_at",
        "is_generated",
    )
    list_filter = ("box", "is_generated", "created_at")
    search_fields = ("question", "answer", "concept_label", "course__name")
    list_select_related = ("course",)
    raw_id_fields = ("course", "material")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Question")
    def question_preview(self, obj):
        return str(obj)
