"""Error pages, accessibility hooks and query counts that stay flat as data grows."""

import pytest
from django.db import connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.views.defaults import server_error
from rest_framework.test import APIClient

from flashcards.generation import embeddings
from flashcards.models import Flashcard
from materials.models import Material
from study.scheduler import record_answer, start_session


def test_404_page(auth_client):
    response = auth_client.get("/courses/999999/")
    assert response.status_code == 404
    assert "We couldn't find that page" in response.text
    assert "Go to your courses" in response.text


def test_csrf_failure_page(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.post(reverse("courses:create"), {"name": "X"})
    assert response.status_code == 403
    assert "Your session needs refreshing" in response.text


def test_500_page_renders_without_a_request_context():
    response = server_error(RequestFactory().get("/"))
    assert response.status_code == 500
    assert b"Something went wrong on our side" in response.content


def test_skip_link_and_current_page(auth_client):
    text = auth_client.get(reverse("courses:list")).text
    assert 'href="#main"' in text and 'id="main"' in text
    assert 'aria-current="page"' in text


def build(user, make_course, count):
    """`count` courses, each with a material, 3 cards and a reviewed session."""
    for i in range(count):
        course = make_course(user, f"Course {i}")
        material = Material.objects.create(
            course=course, title=f"Notes {i}", source_type="text", status="ready"
        )
        session = start_session(course)
        for j in range(3):
            card = Flashcard.objects.create(
                course=course,
                material=material if j else None,
                question=f"Q{i}.{j}",
                answer="A",
                concept_label=f"Concept {j}",
            )
            record_answer(card, j % 2 == 0, session=session)
    return course


def query_counts(user, course):
    web = Client()
    web.force_login(user)
    api = APIClient()
    api.force_authenticate(user)
    urls = [
        (web, reverse("courses:list")),
        (web, course.get_absolute_url()),
        (web, reverse("flashcards:list", args=[course.pk])),
        (web, reverse("study:progress", args=[course.pk])),
        (api, reverse("api:course-list")),
        (api, reverse("api:material-list")),
        (api, reverse("api:flashcard-list")),
        (api, reverse("api:review-list")),
        (api, reverse("api:course-due", args=[course.pk])),
    ]
    counts = []
    for client, url in urls:
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        counts.append(len(queries))
    return counts


@pytest.mark.django_db
def test_query_counts_do_not_grow_with_data(make_user, make_course):
    small_user, big_user = make_user(), make_user()
    small = query_counts(small_user, build(small_user, make_course, 1))
    big = query_counts(big_user, build(big_user, make_course, 8))
    assert small == big


def test_embedding_model_loads_once_per_process(settings, monkeypatch):
    loads = []

    class FakeModel:
        def __init__(self, name):
            loads.append(name)

    monkeypatch.setattr(embeddings, "SentenceTransformerEmbedder", FakeModel)
    embeddings._load_sentence_transformer.cache_clear()
    settings.EMBEDDING_BACKEND = "sentence-transformers"
    try:
        first, second = embeddings.get_embedder(), embeddings.get_embedder()
    finally:
        embeddings._load_sentence_transformer.cache_clear()
    assert first is second
    assert loads == [settings.EMBEDDING_MODEL]
