from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from flashcards.models import Flashcard
from materials.models import Material
from study.models import ReviewLog
from study.scheduler import start_session

from .conftest import PASSWORD
from .pdfs import LECTURE, make_pdf
from .sample_notes import NOTES


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def course(user, make_course):
    return make_course(user)


@pytest.fixture
def card(course):
    return Flashcard.objects.create(course=course, question="What is osmosis?", answer="Water.")


def url(name, *args, **query):
    path = reverse(f"api:{name}", args=args)
    if query:
        path += "?" + "&".join(f"{k}={v}" for k, v in query.items())
    return path


# --- Auth ---------------------------------------------------------------------------


def test_api_requires_authentication(course):
    response = APIClient().get(url("course-list"))
    assert response.status_code == 401


def test_token_auth(user, course):
    client = APIClient()
    response = client.post(url("token"), {"username": user.username, "password": PASSWORD})
    assert response.status_code == 200
    token = response.json()["token"]
    assert Token.objects.get(user=user).key == token

    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    assert client.get(url("course-list")).json()["count"] == 1

    client.credentials(HTTP_AUTHORIZATION="Token wrong")
    assert client.get(url("course-list")).status_code == 401


def test_bad_credentials_get_no_token(user):
    response = APIClient().post(url("token"), {"username": user.username, "password": "nope"})
    assert response.status_code == 400


def test_session_auth_enforces_csrf(user, course):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.get(url("course-list")).status_code == 200
    assert client.post(url("course-list"), {"name": "Chemistry"}).status_code == 403


# --- Courses ------------------------------------------------------------------------


def test_course_crud(api, user):
    created = api.post(url("course-list"), {"name": "  Organic   Chemistry ", "description": "C"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Organic Chemistry"
    assert (body["card_count"], body["due_count"], body["material_count"]) == (0, 0, 0)
    pk = body["id"]

    assert api.post(url("course-list"), {"name": "organic chemistry"}).status_code == 400
    assert api.patch(url("course-detail", pk), {"name": "Chem"}).json()["name"] == "Chem"
    assert api.get(url("course-list")).json()["count"] == 1
    assert api.delete(url("course-detail", pk)).status_code == 204
    assert not user.courses.exists()


def test_course_counts(api, course, card):
    Flashcard.objects.create(
        course=course, question="Later?", answer="A", next_review_at=timezone.now() + timedelta(1)
    )
    body = api.get(url("course-detail", course.pk)).json()
    assert (body["card_count"], body["due_count"]) == (2, 1)


def test_due_cards(api, course):
    now = timezone.now()
    box2 = Flashcard.objects.create(
        course=course, question="B2", answer="A", box=2, next_review_at=now - timedelta(days=3)
    )
    box1 = Flashcard.objects.create(
        course=course, question="B1", answer="A", box=1, next_review_at=now - timedelta(hours=1)
    )
    Flashcard.objects.create(
        course=course, question="Later", answer="A", next_review_at=now + timedelta(days=1)
    )
    body = api.get(url("course-due", course.pk)).json()
    assert body["count"] == 2
    assert [c["id"] for c in body["results"]] == [box1.pk, box2.pk]


# --- Materials ----------------------------------------------------------------------


def test_add_text_material(api, course):
    response = api.post(
        url("material-list"), {"course": course.pk, "source_type": "text", "text": NOTES}
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "ready"  # tasks run inline in tests
    assert body["title"]  # defaults from the first line
    assert body["raw_text"]
    assert Flashcard.objects.filter(material_id=body["id"]).exists()


def test_add_pdf_material(api, course):
    upload = SimpleUploadedFile("week1.pdf", make_pdf(LECTURE), content_type="application/pdf")
    response = api.post(
        url("material-list"),
        {"course": course.pk, "source_type": "pdf", "file": upload},
        format="multipart",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["title"] == "week1"
    assert body["page_count"] == len(LECTURE)
    assert body["file_url"].endswith(reverse("materials:file", args=[body["id"]]))


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"source_type": "text", "text": ""}, "text"),
        ({"source_type": "pdf"}, "file"),
        ({"source_type": "video", "text": "x"}, "source_type"),
    ],
)
def test_material_validation(api, course, data, field):
    response = api.post(url("material-list"), {"course": course.pk, **data}, format="multipart")
    assert response.status_code == 400
    assert field in response.json()


def test_upload_must_be_a_pdf(api, course):
    upload = SimpleUploadedFile("notes.pdf", b"not a pdf at all", content_type="application/pdf")
    response = api.post(
        url("material-list"),
        {"course": course.pk, "source_type": "pdf", "file": upload},
        format="multipart",
    )
    assert response.status_code == 400
    assert "valid PDF" in response.json()["file"][0]


def test_material_list_filter_and_regenerate(api, course, make_course, user):
    other = make_course(user, "Other")
    material = Material.objects.create(
        course=course, title="Notes", source_type="text", raw_text=NOTES, status="ready"
    )
    Material.objects.create(course=other, title="Other", source_type="text", status="ready")

    listed = api.get(url("material-list", course=course.pk)).json()
    assert [m["id"] for m in listed["results"]] == [material.pk]
    assert "raw_text" not in listed["results"][0]
    assert api.get(url("material-list", course="abc")).status_code == 400

    response = api.post(url("material-regenerate", material.pk))
    assert response.status_code == 202
    assert response.json()["status"] == "ready"
    assert material.flashcards.exists()


def test_regenerate_conflicts_while_processing(api, course):
    material = Material.objects.create(
        course=course, title="Notes", source_type="text", status=Material.Status.GENERATING
    )
    assert api.post(url("material-regenerate", material.pk)).status_code == 409


def test_uploads_are_rate_limited(api, course, settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "uploads": "2/hour",
        },
    }
    data = {"course": course.pk, "source_type": "text", "text": "Osmosis is water moving."}
    assert api.post(url("material-list"), data).status_code == 201
    assert api.post(url("material-list"), data).status_code == 201
    response = api.post(url("material-list"), data)
    assert response.status_code == 429
    assert course.materials.count() == 2


def test_generation_is_rate_limited(api, course, settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "generation": "1/hour",
        },
    }
    material = Material.objects.create(
        course=course, title="Notes", source_type="text", raw_text=NOTES, status="ready"
    )
    assert api.post(url("material-regenerate", material.pk)).status_code == 202
    assert api.post(url("material-regenerate", material.pk)).status_code == 429


# --- Flashcards and reviews ---------------------------------------------------------


def test_flashcard_crud(api, course):
    material = Material.objects.create(course=course, title="N", source_type="text")
    created = api.post(
        url("flashcard-list"),
        {
            "course": course.pk,
            "material": material.pk,
            "question": "Q?",
            "answer": "A.",
            "concept_label": "  Cell   biology ",
        },
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert (body["box"], body["concept_label"], body["is_edited"]) == (1, "Cell biology", False)

    pk = body["id"]
    same = api.patch(url("flashcard-detail", pk), {"question": "Q?"}).json()
    assert same["is_edited"] is False
    edited = api.patch(url("flashcard-detail", pk), {"answer": "Better.", "box": 5}).json()
    assert (edited["answer"], edited["is_edited"], edited["box"]) == ("Better.", True, 1)
    assert api.delete(url("flashcard-detail", pk)).status_code == 204


def test_flashcard_filters(api, course, card, make_course, user):
    other = Flashcard.objects.create(
        course=make_course(user, "Other"), question="Q", answer="A", box=3
    )
    assert api.get(url("flashcard-list")).json()["count"] == 2
    assert [c["id"] for c in api.get(url("flashcard-list", box=3)).json()["results"]] == [other.pk]
    assert api.get(url("flashcard-list", course=course.pk)).json()["count"] == 1
    assert api.get(url("flashcard-list", due="true")).json()["count"] == 2
    assert api.get(url("flashcard-list", page_size=1)).json()["next"]


def test_flashcard_material_must_match_course(api, course, make_course, user):
    other_material = Material.objects.create(
        course=make_course(user, "Other"), title="N", source_type="text"
    )
    response = api.post(
        url("flashcard-list"),
        {"course": course.pk, "material": other_material.pk, "question": "Q", "answer": "A"},
    )
    assert response.status_code == 400 and "material" in response.json()


def test_a_card_cannot_move_course(api, card, make_course, user):
    other = make_course(user, "Other")
    api.patch(url("flashcard-detail", card.pk), {"course": other.pk})
    card.refresh_from_db()
    assert card.course_id != other.pk


def test_review(api, card, course):
    response = api.post(url("flashcard-review", card.pk), {"correct": True})
    assert response.status_code == 201
    body = response.json()
    assert (body["review"]["box_before"], body["review"]["box_after"]) == (1, 2)
    assert body["flashcard"]["box"] == 2

    session = start_session(course)
    response = api.post(url("flashcard-review", card.pk), {"correct": False, "session": session.pk})
    assert response.json()["review"]["session"] == session.pk
    session.refresh_from_db()
    assert (session.cards_reviewed, session.cards_correct) == (1, 0)

    history = api.get(url("review-list", flashcard=card.pk)).json()
    assert [r["box_after"] for r in history["results"]] == [1, 2]


def test_review_validation(api, card, course, make_course, user):
    assert api.post(url("flashcard-review", card.pk), {}).status_code == 400
    other_session = start_session(make_course(user, "Other"))
    response = api.post(
        url("flashcard-review", card.pk), {"correct": True, "session": other_session.pk}
    )
    assert response.status_code == 400 and "session" in response.json()
    assert not ReviewLog.objects.exists()


# --- Owner isolation ----------------------------------------------------------------


def test_other_users_data_is_invisible(api, other_user, make_course):
    theirs = make_course(other_user, "Theirs")
    material = Material.objects.create(course=theirs, title="N", source_type="text")
    their_card = Flashcard.objects.create(course=theirs, question="Q", answer="A")
    session = start_session(theirs)
    log_card = Flashcard.objects.create(course=theirs, question="Q2", answer="A")
    from study.scheduler import record_answer

    record_answer(log_card, True, session=session)

    for name in ("course-list", "material-list", "flashcard-list", "review-list"):
        assert api.get(url(name)).json()["count"] == 0

    for name, pk in [
        ("course-detail", theirs.pk),
        ("course-due", theirs.pk),
        ("material-detail", material.pk),
        ("flashcard-detail", their_card.pk),
    ]:
        assert api.get(url(name, pk)).status_code == 404
    assert api.delete(url("course-detail", theirs.pk)).status_code == 404
    assert api.post(url("material-regenerate", material.pk)).status_code == 404
    assert api.post(url("flashcard-review", their_card.pk), {"correct": True}).status_code == 404

    # Their ids can't be used in writes either.
    assert (
        api.post(
            url("flashcard-list"), {"course": theirs.pk, "question": "Q", "answer": "A"}
        ).status_code
        == 400
    )
    assert (
        api.post(
            url("material-list"), {"course": theirs.pk, "source_type": "text", "text": "Hi there"}
        ).status_code
        == 400
    )
    their_card.refresh_from_db()
    assert their_card.box == 1


# --- Schema and docs ----------------------------------------------------------------


def test_schema_and_docs(client):
    schema = client.get(reverse("api:schema"))
    assert schema.status_code == 200
    text = schema.content.decode()
    for path in (
        "/api/v1/courses/{id}/due/",
        "/api/v1/flashcards/{id}/review/",
        "/api/v1/materials/{id}/regenerate/",
        "/api/v1/auth/token/",
    ):
        assert path in text
    assert client.get(reverse("api:docs")).status_code == 200
