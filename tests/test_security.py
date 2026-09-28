"""Cross-cutting security checks: owner isolation, CSRF, upload size, headers, login limits."""

import re

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from flashcards.models import Flashcard
from materials.models import Material
from study.scheduler import start_session

from .conftest import PASSWORD


def named_patterns(resolver=None, namespace=""):
    """(url name, pattern) for every named URL, namespaced like "materials:detail"."""
    for entry in (resolver or get_resolver()).url_patterns:
        if isinstance(entry, URLResolver):
            ns = f"{namespace}{entry.namespace}:" if entry.namespace else namespace
            yield from named_patterns(entry, ns)
        elif isinstance(entry, URLPattern) and entry.name:
            yield f"{namespace}{entry.name}", entry


# Which object each id-taking URL points at, by namespace (or full name).
OWNER_OBJECTS = {
    "courses": "course",
    "materials": "material",
    "flashcards": "card",
    "study": "session",
    "api:course": "course",
    "api:material": "material",
    "api:flashcard": "card",
    "api:review": "review",
}


def object_for(name, kwarg):
    if kwarg == "course_pk":
        return "course"
    for prefix in sorted(OWNER_OBJECTS, key=len, reverse=True):
        if name.startswith(prefix):
            return OWNER_OBJECTS[prefix]
    raise AssertionError(f"Add {name} to OWNER_OBJECTS so its owner check is tested.")


@pytest.fixture
def victim_objects(other_user, make_course):
    course = make_course(other_user, "Private")
    material = Material.objects.create(course=course, title="Notes", source_type="text")
    card = Flashcard.objects.create(course=course, question="Q", answer="A", material=material)
    session = start_session(course)
    from study.scheduler import record_answer

    review = record_answer(card, True, session=session)
    return {
        "course": course,
        "material": material,
        "card": card,
        "session": session,
        "review": review,
    }


def id_urls():
    for name, pattern in named_patterns():
        kwargs = re.findall(r"<int:(\w+)>", str(pattern.pattern))
        # DRF routers use (?P<pk>[^/.]+) instead of converters.
        kwargs += re.findall(r"\(\?P<(pk)>", str(pattern.pattern))
        if kwargs and not name.startswith("admin:"):
            yield name, kwargs


def test_the_sweep_finds_the_id_urls():
    names = {name for name, _ in id_urls()}
    assert {"courses:detail", "materials:file", "study:answer", "api:flashcard-review"} <= names


@pytest.mark.parametrize("method", ["get", "post"])
def test_other_users_objects_are_404_everywhere(client, user, victim_objects, method):
    client.force_login(user)
    checked = 0
    for name, kwargs in id_urls():
        if name.endswith("-detail") and method == "post":
            continue  # detail routes don't take POST: 405 before any lookup
        args = {k: victim_objects[object_for(name, k)].pk for k in kwargs}
        path = reverse(name, kwargs=args)
        response = getattr(client, method)(path)
        assert response.status_code in (404, 405), (
            f"{method.upper()} {path} → {response.status_code}"
        )
        checked += 1
    assert checked >= 15
    card = victim_objects["card"]
    card.refresh_from_db()
    assert card.box == 2 and Flashcard.objects.filter(pk=card.pk).exists()
    assert Material.objects.filter(pk=victim_objects["material"].pk).exists()


# --- CSRF ---------------------------------------------------------------------------


def test_htmx_requests_send_the_csrf_token(user, make_course):
    course = make_course(user)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    delete = reverse("courses:delete", args=[course.pk])

    assert client.post(delete, HTTP_HX_REQUEST="true").status_code == 403

    page = client.get(reverse("courses:list")).text
    token = re.search(r'"X-CSRFToken": "([^"]+)"', page).group(1)
    response = client.post(delete, HTTP_HX_REQUEST="true", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 200
    assert not user.courses.exists()


# --- Request size, headers ----------------------------------------------------------


def test_oversized_uploads_are_refused_before_reading(auth_client, user, make_course, settings):
    settings.MATERIAL_MAX_UPLOAD_MB = 1
    course = make_course(user)
    response = auth_client.post(
        reverse("materials:create", args=[course.pk]),
        data=b"x" * 10,
        content_type="application/pdf",
        CONTENT_LENGTH=str(3 * 1024 * 1024),
    )
    assert response.status_code == 413
    assert "up to 1 MB" in response.text
    assert "Content-Security-Policy" in response


def test_security_headers(client):
    response = client.get(reverse("home"))
    policy = response["Content-Security-Policy"]
    assert "default-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert response["X-Frame-Options"] == "DENY"
    # The CDN scripts are pinned to their exact contents.
    assert response.text.count('integrity="sha384-') == 2


def test_csp_can_be_turned_off(client, settings):
    settings.CONTENT_SECURITY_POLICY = ""
    assert "Content-Security-Policy" not in client.get(reverse("home"))


# --- Login --------------------------------------------------------------------------


def test_failed_logins_are_rate_limited(client, user, settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "login": "3/hour",
        },
    }
    login = reverse("login")
    for _ in range(3):
        response = client.post(login, {"username": user.username, "password": "wrong"})
        assert response.status_code == 200

    # Even the right password is refused until the limit resets.
    response = client.post(login, {"username": user.username, "password": PASSWORD})
    assert response.status_code == 429
    assert "Too many failed sign-ins" in response.text
    assert "_auth_user_id" not in client.session


def test_successful_logins_are_not_counted(client, user, settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "login": "1/hour",
        },
    }
    for _ in range(3):
        response = client.post(reverse("login"), {"username": user.username, "password": PASSWORD})
        assert response.status_code == 302
        client.logout()
