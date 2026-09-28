"""Production plumbing: health checks, JSON logs, production settings, helper scripts."""

import json
import logging
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from django.db import DatabaseError

from parchment import views
from parchment.logging import JsonFormatter

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.django_db
def test_health_check_skips_host_and_https_checks(client, settings):
    settings.ALLOWED_HOSTS = ["parchment.example.com"]
    settings.SECURE_SSL_REDIRECT = True
    response = client.get("/healthz/", HTTP_HOST="localhost")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    # Everything else still gets the usual checks.
    assert client.get("/", HTTP_HOST="localhost").status_code == 400


@pytest.mark.django_db
def test_health_check_reports_a_broken_database(client, monkeypatch):
    class Broken:
        def cursor(self):
            raise DatabaseError("down")

    monkeypatch.setattr(views, "connection", Broken())
    response = client.get("/healthz/")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


def test_json_log_lines():
    record = logging.LogRecord(
        "parchment.test", logging.WARNING, __file__, 1, "Hi %s", ("you",), None
    )
    record.material_id = 7
    entry = json.loads(JsonFormatter().format(record))
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "parchment.test"
    assert entry["message"] == "Hi you"
    assert entry["material_id"] == 7
    assert entry["time"].endswith("+00:00")


def test_json_log_includes_the_request_and_exception(rf, user):
    request = rf.get("/courses/")
    request.user = user
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "django.request", logging.ERROR, __file__, 1, "Oops", (), sys.exc_info()
        )
    record.request = request
    entry = json.loads(JsonFormatter().format(record))
    assert (entry["method"], entry["path"], entry["user_id"]) == ("GET", "/courses/", user.pk)
    assert "ValueError: boom" in entry["exception"]


def test_production_settings():
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "parchment.settings.prod",
        "DJANGO_ALLOWED_HOSTS": "parchment.example.com",
    }
    env.pop("DJANGO_LOG_FORMAT", None)
    env.pop("CACHE_URL", None)
    names = [
        "DEBUG",
        "CACHES['default']['BACKEND']",
        "LOGGING['handlers']['console']['formatter']",
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
        "CSRF_COOKIE_HTTPONLY",
        "SECURE_SSL_REDIRECT",
    ]
    code = (
        "import django; django.setup(); from django.conf import settings as s; "
        f"print({', '.join('s.' + name for name in names)})"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    ).stdout.split()
    assert out == [
        "False",
        "django.core.cache.backends.db.DatabaseCache",
        "json",
        "True",
        "True",
        "True",
        "True",
    ]


def test_gunicorn_config(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "5")
    config = runpy.run_path(str(ROOT / "docker" / "gunicorn.conf.py"))
    assert config["workers"] == 5
    assert config["bind"] == "0.0.0.0:8000"


@pytest.mark.parametrize("script", ["docker/entrypoint.sh", "docker/backup.sh"])
def test_shell_scripts_parse(script):
    subprocess.run(["sh", "-n", str(ROOT / script)], check=True)
