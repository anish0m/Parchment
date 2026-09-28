import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import redirect, render

logger = logging.getLogger(__name__)


def home(request):
    if request.user.is_authenticated:
        return redirect("courses:list")
    return render(request, "home.html")


def healthz(request):
    """Health check used by Docker and load balancers: can the app reach the database?"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.exception("Health check failed: database unreachable")
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


def csrf_failure(request, reason=""):
    """A friendly page for a failed CSRF check (usually an expired or cached form)."""
    return render(request, "403_csrf.html", status=403)
