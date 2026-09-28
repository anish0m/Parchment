from django.apps import AppConfig


class StudyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "study"

    def ready(self):
        from . import checks  # noqa: F401  (registers the system checks)
