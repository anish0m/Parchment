from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string


class MaxRequestSizeMiddleware:
    """Refuses request bodies bigger than any upload we accept, before they're read.

    Django only caps form fields (DATA_UPLOAD_MAX_MEMORY_SIZE); uploaded files would
    otherwise be streamed to disk in full before the form rejects them.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limit = (settings.MATERIAL_MAX_UPLOAD_MB + 1) * 1024 * 1024
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > limit:
            body = render_to_string(
                "413.html", {"limit_mb": settings.MATERIAL_MAX_UPLOAD_MB}, request=None
            )
            response = HttpResponse(body, status=413)
            response["Connection"] = "close"
            return response
        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    """Adds the Content-Security-Policy header (settings.CONTENT_SECURITY_POLICY)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        policy = settings.CONTENT_SECURITY_POLICY
        if policy and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = policy
        return response
