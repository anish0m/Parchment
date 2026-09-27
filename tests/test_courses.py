import pytest
from django.db import IntegrityError
from django.urls import reverse

from courses.models import Course

from .conftest import HTMX


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["list", "create"])
def test_course_pages_require_login(client, name):
    response = client.get(reverse(f"courses:{name}"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_list_shows_only_own_courses(auth_client, user, other_user, make_course):
    make_course(user, "Mine")
    make_course(other_user, "Theirs")

    response = auth_client.get(reverse("courses:list"))

    assert [c.name for c in response.context["courses"]] == ["Mine"]
    assert "Theirs" not in response.content.decode()


def test_list_empty_state(auth_client):
    response = auth_client.get(reverse("courses:list"))

    assert "No courses yet" in response.content.decode()


def test_create_course(auth_client, user):
    response = auth_client.post(
        reverse("courses:create"), {"name": "  Chemistry  ", "description": "Organic"}
    )

    course = Course.objects.get()
    assert course.owner == user
    assert course.name == "Chemistry"
    assert response.status_code == 302
    assert response.url == course.get_absolute_url()


def test_create_course_with_htmx_returns_fresh_form_and_list(auth_client, user):
    response = auth_client.post(reverse("courses:create"), {"name": "Physics"}, **HTMX)

    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="course-form"' in content
    assert 'hx-swap-oob="true"' in content
    assert "Physics" in content
    assert Course.objects.filter(owner=user, name="Physics").exists()


def test_create_course_with_htmx_shows_errors_in_form(auth_client):
    response = auth_client.post(reverse("courses:create"), {"name": ""}, **HTMX)

    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="course-form"' in content
    assert "hx-swap-oob" not in content
    assert "This field is required" in content


def test_duplicate_course_name_is_rejected_case_insensitively(auth_client, user, make_course):
    make_course(user, "History")

    response = auth_client.post(reverse("courses:create"), {"name": "history"})

    assert response.status_code == 200
    assert "already have a course with this name" in response.content.decode()
    assert Course.objects.count() == 1


def test_same_course_name_allowed_for_different_users(auth_client, other_user, make_course):
    make_course(other_user, "History")

    auth_client.post(reverse("courses:create"), {"name": "History"})

    assert Course.objects.filter(name="History").count() == 2


def test_database_enforces_unique_name_per_owner(user, make_course):
    make_course(user, "Maths")

    with pytest.raises(IntegrityError):
        make_course(user, "MATHS")


def test_detail_page(auth_client, user, make_course):
    course = make_course(user, "Geology", description="Rocks")

    response = auth_client.get(course.get_absolute_url())

    assert response.status_code == 200
    assert "Geology" in response.content.decode()


def test_update_course(auth_client, user, make_course):
    course = make_course(user, "Geology")

    response = auth_client.post(
        reverse("courses:update", args=[course.pk]), {"name": "Geology II", "description": ""}
    )

    assert response.status_code == 302
    course.refresh_from_db()
    assert course.name == "Geology II"


def test_update_keeping_same_name_is_allowed(auth_client, user, make_course):
    course = make_course(user, "Geology")

    response = auth_client.post(
        reverse("courses:update", args=[course.pk]), {"name": "Geology", "description": "New"}
    )

    assert response.status_code == 302
    course.refresh_from_db()
    assert course.description == "New"


def test_delete_course(auth_client, user, make_course):
    course = make_course(user)

    response = auth_client.post(reverse("courses:delete", args=[course.pk]))

    assert response.status_code == 302
    assert response.url == reverse("courses:list")
    assert not Course.objects.exists()


def test_delete_course_with_htmx_returns_updated_list(auth_client, user, make_course):
    doomed = make_course(user, "Doomed")
    make_course(user, "Kept")

    response = auth_client.post(reverse("courses:delete", args=[doomed.pk]), **HTMX)

    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="course-list"' in content
    assert "Kept" in content
    assert "Doomed" not in content


@pytest.mark.parametrize(
    "name, method",
    [
        ("detail", "get"),
        ("update", "get"),
        ("update", "post"),
        ("delete", "get"),
        ("delete", "post"),
    ],
)
def test_other_users_course_is_not_found(auth_client, other_user, make_course, name, method):
    course = make_course(other_user, "Private")

    url = reverse(f"courses:{name}", args=[course.pk])
    response = getattr(auth_client, method)(url, {"name": "Hacked"})

    assert response.status_code == 404
    course.refresh_from_db()
    assert course.name == "Private"
