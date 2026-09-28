"""Per-user rate limits on the expensive actions: uploading notes and generating cards.

The same limits apply to the web pages and the API. Rates are in
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] and are counted in the default cache.
"""

from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle


class UserScopedThrottle(SimpleRateThrottle):
    """Counts requests per signed-in user (or per IP address) for one scope."""

    scope = None

    def get_rate(self):
        # Read the settings on each use, so they can be changed without a restart
        # of the class (and overridden in tests).
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        ident = user.pk if user and user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class UploadThrottle(UserScopedThrottle):
    scope = "uploads"


class GenerationThrottle(UserScopedThrottle):
    scope = "generation"


def wait_time(request, throttle_class):
    """For plain Django views: None if the request is allowed (and counts it), else
    the number of seconds to wait."""
    throttle = throttle_class()
    if throttle.allow_request(request, None):
        return None
    return max(int(throttle.wait() or 0), 1)


def describe_wait(seconds):
    minutes = -(-seconds // 60)  # round up
    if minutes <= 1:
        return "a minute"
    if minutes < 60:
        return f"{minutes} minutes"
    hours = -(-minutes // 60)
    return "an hour" if hours == 1 else f"{hours} hours"
