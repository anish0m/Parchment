from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render


def home(request):
    if request.user.is_authenticated:
        return redirect("courses:list")
    return render(request, "home.html")


def healthz(request):
    """Liveness check used by Docker: confirms the app can reach the database."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


def csrf_failure(request, reason=""):
    """A friendly page for a failed CSRF check (usually an expired or cached form)."""
    return render(request, "403_csrf.html", status=403)
