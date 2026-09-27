import pytest
from django.db import IntegrityError
from django.urls import reverse

from courses.models import Course
from courses.views import COURSES_PER_PAGE as PER_PAGE

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


def make_many(make_course, owner, count):
    # Zero-padded so alphabetical order matches creation order.
    return [make_course(owner, f"Course {i:03}") for i in range(count)]


def test_list_is_paginated(auth_client, user, make_course):
    make_many(make_course, user, PER_PAGE + 1)

    first = auth_client.get(reverse("courses:list"))
    second = auth_client.get(reverse("courses:list"), {"page": 2})

    assert len(first.context["courses"]) == PER_PAGE
    assert [c.name for c in second.context["courses"]] == [f"Course {PER_PAGE:03}"]
    assert 'aria-label="Pages"' in first.content.decode()


def test_no_page_links_when_everything_fits(auth_client, user, make_course):
    make_course(user)

    response = auth_client.get(reverse("courses:list"))

    assert 'aria-label="Pages"' not in response.content.decode()


def test_out_of_range_page_shows_last_page(auth_client, user, make_course):
    make_many(make_course, user, PER_PAGE + 1)

    response = auth_client.get(reverse("courses:list"), {"page": 99})

    assert response.status_code == 200
    assert response.context["page_obj"].number == 2


def test_list_ordering_ignores_case(auth_client, user, make_course):
    for name in ["banana", "Apple", "cherry"]:
        make_course(user, name)

    response = auth_client.get(reverse("courses:list"))

    assert [c.name for c in response.context["courses"]] == ["Apple", "banana", "cherry"]


def test_htmx_page_link_returns_only_the_list(auth_client, user, make_course):
    make_many(make_course, user, PER_PAGE + 1)

    response = auth_client.get(
        reverse("courses:list"), {"page": 2}, HTTP_HX_TARGET="course-list", **HTMX
    )

    content = response.content.decode()
    assert content.lstrip().startswith('<div id="course-list"')
    assert "<html" not in content


def test_htmx_history_restore_gets_full_page(auth_client, user, make_course):
    response = auth_client.get(
        reverse("courses:list"),
        HTTP_HX_TARGET="course-list",
        HTTP_HX_HISTORY_RESTORE_REQUEST="true",
        **HTMX,
    )

    assert "<html" in response.content.decode()


def test_htmx_create_shows_the_page_with_the_new_course(auth_client, user, make_course):
    make_many(make_course, user, PER_PAGE)

    response = auth_client.post(reverse("courses:create"), {"name": "Zoology"}, **HTMX)

    assert response.context["page_obj"].number == 2
    assert "Zoology" in response.content.decode()


def test_htmx_delete_stays_on_the_current_page(auth_client, user, make_course):
    courses = make_many(make_course, user, PER_PAGE + 2)

    response = auth_client.post(
        reverse("courses:delete", args=[courses[-1].pk]), {"page": 2}, **HTMX
    )

    assert response.context["page_obj"].number == 2
    assert [c.name for c in response.context["courses"]] == [courses[-2].name]


def test_htmx_delete_of_last_item_on_page_falls_back_to_previous_page(
    auth_client, user, make_course
):
    courses = make_many(make_course, user, PER_PAGE + 1)

    response = auth_client.post(
        reverse("courses:delete", args=[courses[-1].pk]), {"page": 2}, **HTMX
    )

    assert response.context["page_obj"].number == 1
