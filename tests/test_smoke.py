import pytest
from django.core.management import call_command
from django.urls import reverse


@pytest.mark.django_db
def test_home_page_renders_base_layout(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Parchment" in content
    assert "htmx.org" in content
    assert "alpinejs" in content


@pytest.mark.django_db
def test_healthz_reports_database_ok(client):
    response = client.get(reverse("healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_admin_login_page_loads(client):
    response = client.get(reverse("admin:login"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_no_missing_migrations():
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
