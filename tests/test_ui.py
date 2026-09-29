"""The redesigned pages: profile, sign-in landing pages, modals and the processing view."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from courses.models import Course
from courses.templatetags.course_tags import initial, mastery
from flashcards.models import Flashcard
from materials.models import Material
from study.scheduler import record_answer, start_session

from .conftest import HTMX, PASSWORD
from .sample_notes import NOTES


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def course(user, make_course):
    return make_course(user, "Biology 101", description="Cells and more.")


# --- Where sign-in lands ------------------------------------------------------------


def test_login_lands_on_the_course_list(client, user):
    response = client.post(reverse("login"), {"username": user.username, "password": PASSWORD})
    assert response.url == reverse("courses:list")


def test_signup_lands_on_an_empty_profile(client, db):
    response = client.post(
        reverse("signup"),
        {
            "username": "dana",
            "email": "dana@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
        follow=True,
    )
    page = response.content.decode()
    assert response.redirect_chain[-1][0] == reverse("profile")
    assert "@dana" in page
    assert "No courses yet." in page
    assert 'data-open-modal="course-modal"' in page


def test_sign_in_pages_use_the_split_layout(client, db):
    for name in ("login", "signup", "password_reset"):
        page = client.get(reverse(name)).content.decode()
        assert 'class="auth-split"' in page
        assert "img/landing.webp" in page
    assert 'placeholder="Your username"' in client.get(reverse("login")).content.decode()


def test_landing_page(client, db):
    page = client.get(reverse("home")).content.decode()
    assert "Your notes have more to say." in page
    assert reverse("signup") in page and reverse("login") in page


# --- Profile ------------------------------------------------------------------------


def test_profile_shows_stats_and_the_two_latest_courses(auth_client, user, make_course):
    old = make_course(user, "Old course")
    Course.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=30))
    quiet = make_course(user, "Quiet course")
    Course.objects.filter(pk=quiet.pk).update(updated_at=timezone.now() - timedelta(days=20))
    busy = make_course(user, "Busy course")
    Course.objects.filter(pk=busy.pk).update(updated_at=timezone.now() - timedelta(days=40))
    # A new material counts as activity, so the busy course comes first.
    Material.objects.create(course=busy, title="Notes", source_type="text")
    card = Flashcard.objects.create(course=busy, question="Q", answer="A")
    record_answer(card, True, session=start_session(busy))

    response = auth_client.get(reverse("profile"))

    assert response.status_code == 200
    assert [c.name for c in response.context["latest_courses"]] == ["Busy course", "Quiet course"]
    ctx = response.context
    assert (ctx["course_count"], ctx["material_count"], ctx["review_count"]) == (3, 1, 1)
    page = response.content.decode()
    assert "Show all courses" in page
    assert "Member since" in page


def test_profile_requires_login(client):
    assert client.get(reverse("profile")).status_code == 302


def test_user_menu_links(auth_client):
    page = auth_client.get(reverse("courses:list")).content.decode()
    for name in ("profile", "settings", "logout"):
        assert reverse(name) in page
    assert "Change password" not in page
    assert "data-theme-toggle" in page


# --- Courses ------------------------------------------------------------------------


def test_course_list_opens_the_modal_on_request(auth_client):
    page = auth_client.get(reverse("courses:list") + "?new=1").content.decode()
    assert 'id="course-modal" class="modal-backdrop open"' in page


def test_edit_course_in_the_modal(auth_client, course):
    url = reverse("courses:update", args=[course.pk])
    ok = auth_client.post(url, {"name": "Biology 102", "description": ""}, **HTMX)
    assert ok.status_code == 204 and ok["HX-Redirect"] == course.get_absolute_url()

    bad = auth_client.post(url, {"name": ""}, **HTMX)
    assert 'id="course-form"' in bad.content.decode()
    assert f'hx-post="{url}"' in bad.content.decode()
    assert "This field is required" in bad.content.decode()


def test_course_page_has_modals_and_confirmations(auth_client, course):
    page = auth_client.get(course.get_absolute_url()).content.decode()
    for modal in ("course-modal", "material-modal", "processing-modal", "confirm-modal"):
        assert f'id="{modal}"' in page
    assert "data-confirm=" in page  # deleting the course asks first


# --- Materials ----------------------------------------------------------------------


def test_add_material_form_loads_into_the_modal(auth_client, course):
    response = auth_client.get(reverse("materials:create", args=[course.pk]), **HTMX)
    page = response.content.decode()
    assert "<html" not in page
    assert 'hx-target="closest [data-modal-body]"' in page
    assert 'data-close-modal="material-modal"' in page


def test_adding_a_material_in_the_modal_shows_its_progress(auth_client, course):
    response = auth_client.post(
        reverse("materials:create", args=[course.pk]),
        {"source_type": "text", "text": NOTES, "title": "Week 1"},
        **HTMX,
    )
    page = response.content.decode()
    material = Material.objects.get()
    # Tasks run inline in tests, so it's already done.
    assert "Your flashcards are ready." in page
    assert reverse("flashcards:list", args=[course.pk]) + f"?material={material.pk}" in page
    # The course's material list is refreshed alongside.
    assert 'id="material-list" class="list-region" hx-swap-oob="true"' in page


def test_modal_errors_keep_the_form(auth_client, course):
    response = auth_client.post(
        reverse("materials:create", args=[course.pk]), {"source_type": "text", "text": ""}, **HTMX
    )
    page = response.content.decode()
    assert 'id="material-form"' in page
    assert '<input type="hidden" name="source_type" value="text">' in page
    assert not Material.objects.exists()


@pytest.mark.parametrize(
    ("status", "percent", "current"),
    [("pending", 10, "Queued"), ("processing", 35, "Reading"), ("generating", 70, "Finding")],
)
def test_processing_modal_while_in_progress(auth_client, course, status, percent, current):
    material = Material.objects.create(
        course=course, title="Notes", source_type="text", status=status
    )
    url = reverse("materials:status", args=[material.pk]) + "?view=modal"

    page = auth_client.get(url).content.decode()

    assert "We're preparing your material." in page
    assert f'aria-valuenow="{percent}"' in page
    assert f'<li class="current">{current}' in page
    assert f'hx-get="{url}"' in page  # keeps polling


def test_processing_modal_for_a_failed_material(auth_client, course):
    material = Material.objects.create(
        course=course, title="Scan", source_type="pdf", status="failed", error_message="No text."
    )
    page = auth_client.get(
        reverse("materials:status", args=[material.pk]) + "?view=modal"
    ).content.decode()
    assert "We couldn't read this material." in page
    assert "No text." in page
    assert "hx-trigger" not in page  # stops polling


def test_flashcard_filter_sends_processing_materials_to_the_modal(auth_client, course):
    Material.objects.create(course=course, title="Ready one", source_type="text", status="ready")
    busy = Material.objects.create(
        course=course, title="Busy one", source_type="text", status="generating"
    )

    page = auth_client.get(reverse("flashcards:list", args=[course.pk])).content.decode()

    assert "Busy one · Still processing" in page
    assert f'data-status-url="{reverse("materials:status", args=[busy.pk])}?view=modal"' in page
    assert "data-processing-aware" in page


# --- Template filters ---------------------------------------------------------------


@pytest.mark.parametrize(("average", "expected"), [(None, 0), (1, 0), (3, 50), (5, 100), (1.5, 12)])
def test_mastery(average, expected):
    assert mastery(average) == expected


@pytest.mark.parametrize(("name", "expected"), [("biology", "B"), ("  ∑ algebra", "A"), ("✦", "✦")])
def test_initial(name, expected):
    assert initial(name) == expected


# --- Settings -----------------------------------------------------------------------


def test_settings_page_shows_the_sign_up_details(auth_client, user):
    page = auth_client.get(reverse("settings")).content.decode()
    assert f'value="{user.username}"' in page
    assert f'value="{user.email}" readonly' in page
    assert 'name="password-old_password"' in page
    assert 'data-open-modal="delete-account-modal"' in page


def test_settings_changes_the_username(auth_client, user):
    response = auth_client.post(
        reverse("settings"), {"action": "username", "account-username": "alice2"}
    )
    assert response.url == reverse("settings")
    user.refresh_from_db()
    assert user.username == "alice2"


def test_settings_rejects_a_taken_username_in_any_case(auth_client, user, other_user):
    response = auth_client.post(
        reverse("settings"), {"action": "username", "account-username": "BOB"}
    )
    assert response.status_code == 400
    assert "already exists" in response.content.decode()
    user.refresh_from_db()
    assert user.username == "alice"


def test_settings_changes_the_password_and_keeps_you_signed_in(auth_client, user):
    new = "a-brand-new-passphrase-42"
    response = auth_client.post(
        reverse("settings"),
        {
            "action": "password",
            "password-old_password": PASSWORD,
            "password-new_password1": new,
            "password-new_password2": new,
        },
    )
    assert response.url == reverse("settings")
    user.refresh_from_db()
    assert user.check_password(new)
    assert auth_client.get(reverse("profile")).status_code == 200


def test_settings_password_needs_the_old_password(auth_client, user):
    response = auth_client.post(
        reverse("settings"),
        {
            "action": "password",
            "password-old_password": "wrong",
            "password-new_password1": "a-brand-new-passphrase-42",
            "password-new_password2": "a-brand-new-passphrase-42",
        },
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_delete_account_with_wrong_password_reopens_the_modal(auth_client, user):
    response = auth_client.post(reverse("delete_account"), {"password": "wrong"})
    assert response.status_code == 400
    page = response.content.decode()
    assert 'id="delete-account-modal" class="modal-backdrop open"' in page
    assert "That password is incorrect." in page
    assert type(user).objects.filter(pk=user.pk).exists()


def test_delete_account_removes_the_user_and_their_courses(auth_client, user, course):
    response = auth_client.post(reverse("delete_account"), {"password": PASSWORD}, follow=True)
    assert response.redirect_chain[-1][0] == reverse("home")
    assert "has been deleted" in response.content.decode()
    assert not type(user).objects.filter(pk=user.pk).exists()
    assert not Course.objects.filter(pk=course.pk).exists()
    assert auth_client.get(reverse("profile")).status_code == 302


def test_delete_account_needs_post(auth_client):
    assert auth_client.get(reverse("delete_account")).status_code == 405
