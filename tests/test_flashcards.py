import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from flashcards.models import Flashcard
from flashcards.views import CARDS_PER_PAGE
from materials.models import Material

from .conftest import HTMX


@pytest.fixture
def course(user, make_course):
    return make_course(user, "Biology")


@pytest.fixture
def material(course):
    return Material.objects.create(
        course=course, title="Week 1", source_type="text", raw_text="x", status="ready"
    )


@pytest.fixture
def make_card(course):
    def make(question="What is osmosis?", answer="Water moving.", **kwargs):
        kwargs.setdefault("course", course)
        return Flashcard.objects.create(question=question, answer=answer, **kwargs)

    return make


def list_url(course, **params):
    url = reverse("flashcards:list", args=[course.pk])
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return url


def htmx_from(url):
    """Headers for an HTMX request made from the page at `url`."""
    return {**HTMX, "HTTP_HX_CURRENT_URL": "http://testserver" + url}


# --- Model -------------------------------------------------------------------


def test_new_card_defaults(make_card):
    card = make_card()

    assert card.box == 1
    assert card.next_review_at <= timezone.now()
    assert card.is_generated is False


def test_box_must_be_in_range(make_card):
    with pytest.raises(IntegrityError):
        make_card(box=6)


def test_deleting_a_material_keeps_its_cards(make_card, material):
    card = make_card(material=material)

    material.delete()

    card.refresh_from_db()
    assert card.material is None


def test_deleting_a_course_deletes_its_cards(make_card, course):
    make_card()

    course.delete()

    assert not Flashcard.objects.exists()


# --- List --------------------------------------------------------------------


def test_list_requires_login(client, course):
    response = client.get(list_url(course))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_list_groups_cards_by_concept_with_unlabelled_last(auth_client, course, make_card):
    make_card("Q no concept")
    make_card("Q enzymes", concept_label="enzymes")
    make_card("Q cells", concept_label="Cells")

    response = auth_client.get(list_url(course))

    assert [c.question for c in response.context["cards"]] == [
        "Q cells",
        "Q enzymes",
        "Q no concept",
    ]
    content = response.content.decode()
    assert content.index("Cells") < content.index("enzymes") < content.index("No concept")


def test_list_filters_by_material_box_and_hand_added(auth_client, course, make_card, material):
    make_card("Q generated box 1", material=material)
    make_card("Q generated box 3", material=material, box=3)
    make_card("Q by hand box 3", box=3)

    def questions(**params):
        response = auth_client.get(list_url(course, **params))
        return sorted(c.question for c in response.context["cards"])

    assert questions(material=material.pk) == ["Q generated box 1", "Q generated box 3"]
    assert questions(material="none") == ["Q by hand box 3"]
    assert questions(box=3) == ["Q by hand box 3", "Q generated box 3"]
    assert questions(material=material.pk, box=3) == ["Q generated box 3"]


def test_invalid_filters_are_ignored(auth_client, course, make_card):
    make_card()

    response = auth_client.get(list_url(course, material="abc", box=99))

    assert response.status_code == 200
    assert len(response.context["cards"]) == 1


def test_filtered_empty_state(auth_client, course, make_card):
    make_card()

    content = auth_client.get(list_url(course, box=5)).content.decode()

    assert "No cards match these filters" in content


def test_list_is_paginated_and_page_links_keep_filters(auth_client, course, make_card):
    for i in range(CARDS_PER_PAGE + 1):
        make_card(f"Q{i:03}", box=2)

    first = auth_client.get(list_url(course, box=2))
    second = auth_client.get(list_url(course, box=2, page=2))

    assert len(first.context["cards"]) == CARDS_PER_PAGE
    assert len(second.context["cards"]) == 1
    assert "?box=2&amp;page=2" in first.content.decode()


def test_htmx_filter_returns_only_the_list(auth_client, course, make_card):
    make_card()

    response = auth_client.get(list_url(course, box=1), HTTP_HX_TARGET="card-list", **HTMX)

    content = response.content.decode()
    assert content.lstrip().startswith('<div id="card-list"')
    assert "<html" not in content


def test_other_users_course_cards_are_not_found(auth_client, other_user, make_course):
    theirs = make_course(other_user, "Theirs")

    assert auth_client.get(list_url(theirs)).status_code == 404
    response = auth_client.post(
        reverse("flashcards:create", args=[theirs.pk]), {"question": "Q", "answer": "A"}
    )
    assert response.status_code == 404
    assert not Flashcard.objects.exists()


# --- Adding ------------------------------------------------------------------


def test_add_card(auth_client, course, material):
    response = auth_client.post(
        reverse("flashcards:create", args=[course.pk]),
        {
            "question": " What is ATP? ",
            "answer": "Energy currency",
            "concept_label": "  Cell   energy ",
            "material": material.pk,
        },
    )

    card = Flashcard.objects.get()
    assert response.status_code == 302
    assert card.course == course
    assert card.question == "What is ATP?"
    assert card.concept_label == "Cell energy"
    assert card.material == material
    assert card.is_generated is False


def test_add_card_with_htmx_returns_blank_form_and_refreshed_list(auth_client, course):
    url = list_url(course, box=1)

    response = auth_client.post(
        reverse("flashcards:create", args=[course.pk]),
        {"question": "Q new", "answer": "A"},
        **htmx_from(url),
    )

    content = response.content.decode()
    assert "Card added" in content
    assert 'id="card-form"' in content
    assert 'id="card-list" class="list-region" hx-swap-oob="true"' in content
    assert "Q new" in content
    assert response.context["filter_form"].data["box"] == "1"  # kept the page's filter


@pytest.mark.parametrize(
    "data, error",
    [
        ({"question": "", "answer": "A"}, "This field is required"),
        ({"question": "Q", "answer": "   "}, "This field is required"),
        ({"question": "Q" * 2001, "answer": "A"}, "at most 2000 characters"),
    ],
)
def test_add_card_validation(auth_client, course, data, error):
    response = auth_client.post(reverse("flashcards:create", args=[course.pk]), data, **HTMX)

    assert error in response.content.decode()
    assert not Flashcard.objects.exists()


def test_cannot_attach_another_courses_material(auth_client, course, user, make_course):
    other_course = make_course(user, "Chemistry")
    foreign = Material.objects.create(course=other_course, title="Chem", source_type="text")

    response = auth_client.post(
        reverse("flashcards:create", args=[course.pk]),
        {"question": "Q", "answer": "A", "material": foreign.pk},
    )

    assert "Select a valid choice" in response.content.decode()
    assert not Flashcard.objects.exists()


# --- Editing -----------------------------------------------------------------


def test_edit_in_place(auth_client, make_card):
    card = make_card()
    url = reverse("flashcards:update", args=[card.pk])

    form = auth_client.get(url, **HTMX)
    saved = auth_client.post(url, {"question": "Edited?", "answer": "Yes"}, **HTMX)
    cancel = auth_client.get(reverse("flashcards:detail", args=[card.pk]), **HTMX)

    assert f'<li class="flashcard editing" id="card-{card.pk}"' in form.content.decode()
    assert f'<li class="flashcard" id="card-{card.pk}"' in saved.content.decode()
    assert "Edited?" in saved.content.decode()
    assert "Edited?" in cancel.content.decode()
    card.refresh_from_db()
    assert card.question == "Edited?"


def test_edit_in_place_shows_errors_in_the_form(auth_client, make_card):
    card = make_card()

    response = auth_client.post(
        reverse("flashcards:update", args=[card.pk]), {"question": "", "answer": "A"}, **HTMX
    )

    assert "flashcard editing" in response.content.decode()
    assert "This field is required" in response.content.decode()


def test_edit_without_javascript_uses_a_full_page(auth_client, course, make_card):
    card = make_card()
    url = reverse("flashcards:update", args=[card.pk])

    page = auth_client.get(url)
    response = auth_client.post(url, {"question": "Edited?", "answer": "Yes"})

    assert "<html" in page.content.decode()
    assert response.status_code == 302
    assert response.url == list_url(course)


def test_editing_keeps_study_progress(auth_client, make_card):
    card = make_card(box=4)

    auth_client.post(reverse("flashcards:update", args=[card.pk]), {"question": "Q", "answer": "A"})

    card.refresh_from_db()
    assert card.box == 4


# --- Deleting ----------------------------------------------------------------


def test_delete_card(auth_client, course, make_card):
    card = make_card()

    response = auth_client.post(reverse("flashcards:delete", args=[card.pk]))

    assert response.status_code == 302
    assert not Flashcard.objects.exists()


def test_htmx_delete_rerenders_the_list_with_the_same_filters_and_page(
    auth_client, course, make_card
):
    cards = [make_card(f"Q{i:03}", box=2) for i in range(CARDS_PER_PAGE + 2)]
    make_card("Q other box", box=5)
    url = list_url(course, box=2, page=2)

    response = auth_client.post(reverse("flashcards:delete", args=[cards[-1].pk]), **htmx_from(url))

    assert response.context["page_obj"].number == 2
    assert [c.question for c in response.context["cards"]] == [cards[-2].question]


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
def test_other_users_cards_are_not_found(
    auth_client, other_user, make_course, make_card, name, method
):
    card = make_card(course=make_course(other_user, "Theirs"), question="Private")

    url = reverse(f"flashcards:{name}", args=[card.pk])
    response = getattr(auth_client, method)(url, {"question": "Hacked", "answer": "x"})

    assert response.status_code == 404
    card.refresh_from_db()
    assert card.question == "Private"


# --- Course pages and seeding ------------------------------------------------


def test_course_pages_show_card_counts(auth_client, course, make_card, material):
    make_card(material=material)
    make_card()

    card = auth_client.get(reverse("courses:list")).content.decode()
    detail = auth_client.get(course.get_absolute_url()).content.decode()

    assert "1 material · 2 cards" in card
    assert "2 cards." in detail


def test_seed_command(user):
    call_command("seed_flashcards", user.username, "--count", "25")
    call_command("seed_flashcards", user.username, "--count", "5", "--reset")

    cards = Flashcard.objects.filter(course__owner=user)
    assert cards.count() == 5
    assert all(1 <= c.box <= 5 for c in cards)


def test_seed_command_unknown_user(db):
    with pytest.raises(CommandError, match="No user called"):
        call_command("seed_flashcards", "ghost")


def test_list_page_has_no_duplicate_ids(auth_client, course, make_card):
    import re
    from collections import Counter

    make_card()
    content = auth_client.get(list_url(course)).content.decode()

    ids = Counter(re.findall(r'\sid="([^"]+)"', content))
    assert [i for i, n in ids.items() if n > 1] == []
