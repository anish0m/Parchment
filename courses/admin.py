from django.contrib import admin

from .models import Course


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("name", "description", "owner__username", "owner__email")
    list_select_related = ("owner",)
    raw_id_fields = ("owner",)
