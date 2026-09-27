from django.contrib import admin

from .models import Material


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "source_type", "status", "page_count", "created_at")
    list_filter = ("source_type", "status", "created_at")
    search_fields = ("title", "original_filename", "course__name", "course__owner__username")
    list_select_related = ("course",)
    raw_id_fields = ("course",)
    readonly_fields = ("created_at", "updated_at")
