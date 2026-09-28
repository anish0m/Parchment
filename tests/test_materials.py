import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from courses.models import Course
from materials.models import Material
from materials.services import create_material
from materials.views import MATERIALS_PER_PAGE

from .conftest import HTMX
from .pdfs import LECTURE, make_encrypted_pdf, make_pdf


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def course(user, make_course):
    return make_course(user, "Biology")


def pdf_upload(data=None, name="Lecture_1.pdf"):
    return SimpleUploadedFile(
        name, make_pdf(LECTURE) if data is None else data, content_type="application/pdf"
    )


def add_url(course):
    return reverse("materials:create", args=[course.pk])


def post_text(client, course, text="Osmosis\nWater moves across a membrane.", **extra):
    return client.post(add_url(course), {"source_type": "text", "text": text, **extra})


def post_pdf(client, course, upload=None, **extra):
    return client.post(
        add_url(course), {"source_type": "pdf", "file": upload or pdf_upload(), **extra}
    )


def stored_files(root):
    return sorted(p.name for p in root.rglob("*") if p.is_file())


# --- Adding materials -------------------------------------------------------


def test_add_page_requires_login(client, course):
    response = client.get(add_url(course))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_add_page_renders_both_modes(auth_client, course):
    content = auth_client.get(add_url(course)).content.decode()

    assert 'x-model="mode"' in content
    assert 'name="text"' in content
    assert 'name="file"' in content


def test_add_pasted_text(auth_client, course):
    response = post_text(auth_client, course, text="  Osmosis  \n\n\n\nWater   moves.  ")

    material = Material.objects.get()
    assert response.status_code == 302
    assert response.url == material.get_absolute_url()
    assert material.course == course
    assert material.source_type == "text"
    assert material.status == "ready"
    assert material.title == "Osmosis"
    assert material.raw_text == "Osmosis\n\nWater moves."
    assert material.word_count == 3
    assert not material.file


def test_add_pdf(auth_client, course, media_root):
    response = post_pdf(auth_client, course, title="Week 1")

    material = Material.objects.get()
    assert response.status_code == 302
    assert material.status == "ready"
    assert material.title == "Week 1"
    assert material.source_type == "pdf"
    assert material.original_filename == "Lecture_1.pdf"
    assert material.page_count == 3
    assert "Calvin cycle" in material.raw_text
    assert material.file.name.startswith(f"materials/{course.pk}/")
    assert material.file.name.endswith(".pdf")
    assert "Lecture_1" not in material.file.name
    assert len(stored_files(media_root)) == 1


def test_pdf_title_defaults_to_file_name(auth_client, course):
    post_pdf(auth_client, course)

    assert Material.objects.get().title == "Lecture 1"


def test_long_first_line_is_shortened_for_the_default_title(auth_client, course):
    post_text(auth_client, course, text="word " * 40)

    title = Material.objects.get().title
    assert len(title) == 80
    assert title.endswith("…")


@pytest.mark.parametrize(
    "data, error",
    [
        ({"source_type": "text", "text": "   "}, "Paste some notes"),
        ({"source_type": "pdf"}, "Choose a PDF"),
        ({"source_type": "video"}, "Select a valid choice"),
    ],
)
def test_missing_content_is_rejected(auth_client, course, data, error):
    response = auth_client.post(add_url(course), data)

    assert response.status_code == 200
    assert error in response.content.decode()
    assert not Material.objects.exists()


def test_text_mode_ignores_an_attached_file(auth_client, course, media_root):
    post_text(auth_client, course, file=pdf_upload())

    assert Material.objects.get().source_type == "text"
    assert stored_files(media_root) == []


def test_non_pdf_extension_is_rejected(auth_client, course):
    response = post_pdf(auth_client, course, pdf_upload(name="notes.docx"))

    assert "Only PDF files" in response.content.decode()
    assert not Material.objects.exists()


def test_file_that_is_not_really_a_pdf_is_rejected(auth_client, course):
    response = post_pdf(auth_client, course, pdf_upload(b"MZ\x90\x00 an executable"))

    assert "isn&#x27;t a valid PDF" in response.content.decode()
    assert not Material.objects.exists()


def test_empty_file_is_rejected(auth_client, course):
    response = post_pdf(auth_client, course, pdf_upload(b""))

    assert response.status_code == 200
    assert not Material.objects.exists()


def test_file_size_limit(auth_client, course, settings):
    settings.MATERIAL_MAX_UPLOAD_MB = 1

    big = make_pdf(LECTURE) + b"%" * (1024 * 1024)
    response = post_pdf(auth_client, course, pdf_upload(big))

    assert "the limit is 1.0" in response.content.decode()
    assert not Material.objects.exists()


def test_text_length_limit(auth_client, course, settings):
    settings.MATERIAL_MAX_TEXT_CHARS = 10

    response = post_text(auth_client, course, text="x" * 11)

    assert "the limit is 10" in response.content.decode()
    assert not Material.objects.exists()


@pytest.mark.parametrize(
    "data, message",
    [
        (make_pdf([None]), "No text was found"),
        (make_encrypted_pdf(LECTURE), "password-protected"),
        (b"%PDF-1.4\ncorrupt", "couldn&#x27;t be read"),
    ],
    ids=["scanned", "encrypted", "corrupt"],
)
def test_unreadable_pdf_is_saved_as_failed_with_the_reason(auth_client, course, data, message):
    response = post_pdf(auth_client, course, pdf_upload(data))

    material = Material.objects.get()
    assert material.status == "failed"
    assert material.raw_text == ""
    detail = auth_client.get(response.url).content.decode()
    assert message in detail
    assert "Couldn&#x27;t process" in detail  # flash message


def test_cannot_add_to_another_users_course(auth_client, other_user, make_course):
    theirs = make_course(other_user, "Theirs")

    assert auth_client.get(add_url(theirs)).status_code == 404
    assert post_text(auth_client, theirs).status_code == 404
    assert not Material.objects.exists()


# --- Viewing ----------------------------------------------------------------


def test_detail_shows_extracted_text(auth_client, course):
    post_pdf(auth_client, course)
    material = Material.objects.get()

    content = auth_client.get(material.get_absolute_url()).content.decode()

    assert "Extracted text" in content
    assert "Calvin cycle" in content
    assert reverse("materials:file", args=[material.pk]) in content


def test_file_view_serves_the_original_pdf(auth_client, course):
    post_pdf(auth_client, course)
    material = Material.objects.get()

    response = auth_client.get(reverse("materials:file", args=[material.pk]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert 'filename="Lecture_1.pdf"' in response["Content-Disposition"]
    assert b"".join(response.streaming_content) == make_pdf(LECTURE)


def test_file_view_404s_for_pasted_text(auth_client, course):
    post_text(auth_client, course)
    material = Material.objects.get()

    assert auth_client.get(reverse("materials:file", args=[material.pk])).status_code == 404


def test_media_files_are_not_served_publicly(auth_client, course):
    post_pdf(auth_client, course)
    material = Material.objects.get()

    assert auth_client.get("/media/" + material.file.name).status_code == 404


@pytest.mark.parametrize(
    "name, method",
    [("detail", "get"), ("file", "get"), ("delete", "get"), ("delete", "post")],
)
def test_other_users_materials_are_not_found(auth_client, other_user, make_course, name, method):
    material = create_material(
        make_course(other_user, "Theirs"), title="Theirs", source_type="pdf", upload=pdf_upload()
    )

    response = getattr(auth_client, method)(reverse(f"materials:{name}", args=[material.pk]))

    assert response.status_code == 404
    assert Material.objects.exists()


# --- Course page list -------------------------------------------------------


def test_course_page_lists_materials(auth_client, course):
    post_text(auth_client, course, text="Osmosis notes")
    post_pdf(auth_client, course, pdf_upload(make_pdf([None]), name="scan.pdf"))

    content = auth_client.get(course.get_absolute_url()).content.decode()

    assert "Osmosis notes" in content
    assert "scan" in content
    assert "status-ready" in content
    assert "status-failed" in content


def test_course_page_material_list_is_paginated(auth_client, course):
    Material.objects.bulk_create(
        Material(course=course, title=f"Note {i}", source_type="text", status="ready")
        for i in range(MATERIALS_PER_PAGE + 1)
    )

    first = auth_client.get(course.get_absolute_url())
    fragment = auth_client.get(
        course.get_absolute_url(), {"page": 2}, HTTP_HX_TARGET="material-list", **HTMX
    )

    assert len(first.context["materials"]) == MATERIALS_PER_PAGE
    assert len(fragment.context["materials"]) == 1
    content = fragment.content.decode()
    assert content.lstrip().startswith('<div id="material-list"')
    assert "<html" not in content


def test_course_card_shows_material_count(auth_client, course):
    post_text(auth_client, course)
    post_text(auth_client, course, text="Second note")

    content = auth_client.get(reverse("courses:list")).content.decode()

    assert "2 materials" in content


# --- Deleting ---------------------------------------------------------------


def test_delete_removes_the_material_and_its_file(
    auth_client, course, media_root, django_capture_on_commit_callbacks
):
    post_pdf(auth_client, course)
    material = Material.objects.get()

    with django_capture_on_commit_callbacks(execute=True):
        response = auth_client.post(reverse("materials:delete", args=[material.pk]))

    assert response.status_code == 302
    assert response.url == course.get_absolute_url()
    assert not Material.objects.exists()
    assert stored_files(media_root) == []


def test_htmx_delete_returns_the_updated_list(auth_client, course):
    post_text(auth_client, course, text="Keep me")
    post_text(auth_client, course, text="Delete me")
    doomed = Material.objects.get(title="Delete me")

    response = auth_client.post(reverse("materials:delete", args=[doomed.pk]), **HTMX)

    content = response.content.decode()
    assert 'id="material-list"' in content
    assert "Keep me" in content
    assert "Delete me" not in content


def test_deleting_a_course_removes_its_material_files(
    auth_client, course, media_root, django_capture_on_commit_callbacks
):
    post_pdf(auth_client, course)
    post_pdf(auth_client, course)
    assert len(stored_files(media_root)) == 2

    with django_capture_on_commit_callbacks(execute=True):
        auth_client.post(reverse("courses:delete", args=[course.pk]))

    assert not Course.objects.exists()
    assert stored_files(media_root) == []
