from django.conf import settings
from django.core.checks import Error, register

from flashcards.models import LEITNER_BOXES


@register()
def leitner_intervals(app_configs, **kwargs):
    intervals = getattr(settings, "LEITNER_INTERVAL_DAYS", None)
    valid = (
        isinstance(intervals, list | tuple)
        and len(intervals) == LEITNER_BOXES
        and all(isinstance(days, int) and days >= 1 for days in intervals)
        and list(intervals) == sorted(intervals)
    )
    if valid:
        return []
    return [
        Error(
            f"LEITNER_INTERVAL_DAYS must list {LEITNER_BOXES} whole numbers of days (one per "
            f"box), each at least 1 and none shorter than the box before; got {intervals!r}.",
            id="study.E001",
        )
    ]
