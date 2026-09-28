from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from flashcards.models import Flashcard
from materials.models import Material
from study.models import ReviewLog, StudySession
from study.scheduler import PRACTICE_SESSION_CARDS, record_answer, start_session
from study.stats import session_summary, study_streak

from .conftest import HTMX

NOW = datetime(2030, 5, 1, 15, 30, tzinfo=ZoneInfo("UTC"))


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: NOW)


@pytest.fixture
def course(user, make_course):
    return make_course(user)


@pytest.fixture
def make_card(course):
    def make(question="What is osmosis?", due_in=timedelta(hours=-1), **kwargs):
        return Flashcard.objects.create(
            course=course,
            question=question,
            answer=f"Answer to {question}",
            next_review_at=NOW + due_in,
            **kwargs,
        )

    return make


def start_url(course):
    return reverse("study:start", args=[course.pk])


def answer(client, session, card, correct, htmx=True):
    return client.post(
        reverse("study:answer", args=[session.pk]),
        {"card": card.pk, "correct": "1" if correct else "0"},
        **(HTMX if htmx else {}),
    )


# --- Course page and dashboard ----------------------------------------------------


def test_course_page_with_nothing_to_study(auth_client, course):
    response = auth_client.get(course.get_absolute_url())
    assert "No flashcards yet" in response.text
    assert start_url(course) not in response.text


def test_course_page_polls_while_cards_are_generating(auth_client, course):
    Material.objects.create(
        course=course, title="Notes", source_type="text", status=Material.Status.GENERATING
    )
    response = auth_client.get(course.get_absolute_url())
    assert "will appear here when they're ready" in response.text
    assert 'hx-trigger="every 5s"' in response.text

    panel = auth_client.get(reverse("study:panel", args=[course.pk]))
    assert panel.status_code == 200 and "Generating cards" in panel.text


def test_course_page_shows_due_cards(auth_client, course, make_card):
    make_card("A")
    make_card("B")
    make_card("Later", due_in=timedelta(days=3))
    response = auth_client.get(course.get_absolute_url())
    assert "<strong>2</strong> cards due" in response.text
    assert "Study now" in response.text
    assert "every 5s" not in response.text


def test_course_page_offers_study_anyway(auth_client, course, make_card):
    make_card(due_in=timedelta(days=1, hours=1))
    response = auth_client.get(course.get_absolute_url())
    assert "Nothing due today." in response.text
    # naturalday reads the real clock, so the frozen "tomorrow" shows as a date.
    assert "Next card due May 2." in response.text
    assert 'value="practice"' in response.text


def test_dashboard_shows_due_counts(auth_client, user, make_course, make_card):
    make_card("Due")
    make_card("Not due", due_in=timedelta(days=2))
    idle = make_course(user, "Idle")
    Flashcard.objects.create(
        course=idle, question="Q", answer="A", next_review_at=NOW + timedelta(days=1)
    )
    response = auth_client.get(reverse("courses:list"))
    assert "Study 1 due" in response.text
    assert "Nothing due today" in response.text


# --- Starting a session -----------------------------------------------------------


def test_start_requires_login_and_post(auth_client, course, make_card):
    make_card()
    assert Client().post(start_url(course)).status_code == 302
    assert not StudySession.objects.exists()
    assert auth_client.get(start_url(course)).status_code == 405


def test_start_is_limited_to_the_owner(client, other_user, course, make_card):
    make_card()
    client.force_login(other_user)
    assert client.post(start_url(course)).status_code == 404


def test_start_with_no_cards_or_nothing_due(auth_client, course, make_card):
    response = auth_client.post(start_url(course), follow=True)
    assert "no flashcards to study" in response.text

    make_card(due_in=timedelta(days=1))
    response = auth_client.post(start_url(course), follow=True)
    assert "Nothing is due right now" in response.text
    assert not StudySession.objects.exists()


def test_start_opens_a_session(auth_client, course, make_card, user):
    make_card()
    response = auth_client.post(start_url(course))
    session = StudySession.objects.get()
    assert response.url == session.get_absolute_url()
    assert (session.user, session.course, session.mode) == (user, course, "due")


def test_starting_again_closes_the_open_session(auth_client, course, make_card):
    make_card("A")
    make_card("B")
    old = start_session(course, now=NOW - timedelta(hours=2))
    record_answer(course.flashcards.first(), True, session=old, now=NOW - timedelta(hours=1))

    auth_client.post(start_url(course))

    old.refresh_from_db()
    assert old.ended_at == NOW - timedelta(hours=1)
    assert StudySession.objects.filter(ended_at__isnull=True).count() == 1


# --- The session ------------------------------------------------------------------


def test_session_shows_lowest_box_first(auth_client, course, make_card):
    make_card("Box 3", box=3, due_in=timedelta(days=-5))
    make_card("Box 1", box=1)
    auth_client.post(start_url(course))
    session = StudySession.objects.get()

    response = auth_client.get(session.get_absolute_url())

    assert response.status_code == 200
    assert response.context["card"].question == "Box 1"
    assert "Card 1 of 2" in response.text
    assert "Answer to Box 1" in response.text  # on the back of the card


def test_session_is_private(client, other_user, course, make_card):
    make_card()
    session = start_session(course)
    client.force_login(other_user)
    assert client.get(session.get_absolute_url()).status_code == 404
    assert answer(client, session, course.flashcards.get(), True).status_code == 404
    assert client.post(reverse("study:end", args=[session.pk])).status_code == 404
    assert not ReviewLog.objects.exists()


def test_a_whole_session(auth_client, course, make_card):
    """Answer every due card through HTMX, then see the summary."""
    cards = [make_card(f"Card {i}", box=i + 1) for i in range(3)]
    auth_client.post(start_url(course))
    session = StudySession.objects.get()

    first = answer(auth_client, session, cards[0], True)
    assert first.status_code == 200
    assert first.context["card"] == cards[1]
    assert "Card 2 of 3" in first.text
    assert "<html" not in first.text  # a fragment, not a page

    answer(auth_client, session, cards[1], False)
    last = answer(auth_client, session, cards[2], True)

    assert "Session complete" in last.text
    summary = last.context["summary"]
    assert (summary.reviewed, summary.correct, summary.accuracy) == (3, 2, 67)
    assert (summary.promoted, summary.demoted) == (2, 1)
    assert summary.due_now == 0
    session.refresh_from_db()
    assert session.ended_at == NOW
    assert [c.box for c in Flashcard.objects.order_by("pk")] == [2, 1, 4]
    assert "The next card is due Thursday, May 2" in last.text


def test_repeated_answers_are_ignored(auth_client, course, make_card):
    card = make_card(box=2)
    make_card("Other")
    session = start_session(course)

    answer(auth_client, session, card, True)
    answer(auth_client, session, card, True)  # a double click

    assert ReviewLog.objects.count() == 1
    card.refresh_from_db()
    assert card.box == 3


def test_answer_validation(auth_client, course, make_card, user, make_course):
    card = make_card()
    session = start_session(course)
    url = reverse("study:answer", args=[session.pk])

    assert auth_client.post(url, {"card": card.pk, "correct": "maybe"}).status_code == 400
    assert auth_client.post(url, {"correct": "1"}).status_code == 404
    assert auth_client.post(url, {"card": "abc", "correct": "1"}).status_code == 404
    other = Flashcard.objects.create(course=make_course(user, "Other"), question="Q", answer="A")
    assert auth_client.post(url, {"card": other.pk, "correct": "1"}).status_code == 404
    assert auth_client.get(url).status_code == 405
    assert not ReviewLog.objects.exists()


def test_answer_without_htmx_redirects(auth_client, course, make_card):
    card = make_card()
    make_card("Next")
    session = start_session(course)
    response = answer(auth_client, session, card, True, htmx=False)
    assert response.status_code == 302 and response.url == session.get_absolute_url()
    assert ReviewLog.objects.count() == 1


def test_ending_early(auth_client, course, make_card):
    card = make_card()
    make_card("Unseen")
    session = start_session(course)
    answer(auth_client, session, card, False)

    response = auth_client.post(reverse("study:end", args=[session.pk]), **HTMX)

    assert "Session ended" in response.text
    assert "1 card is still due" in response.text
    assert "Keep studying" in response.text
    session.refresh_from_db()
    assert session.ended_at == NOW
    # An answer sent after the end is not recorded.
    answer(auth_client, session, course.flashcards.get(question="Unseen"), True)
    assert ReviewLog.objects.count() == 1
    # Reloading the page shows the summary again.
    assert "Session ended" in auth_client.get(session.get_absolute_url()).text


def test_ending_with_no_answers(auth_client, course, make_card):
    make_card()
    session = start_session(course)
    response = auth_client.post(reverse("study:end", args=[session.pk]))
    assert response.url == session.get_absolute_url()
    assert "didn't answer any cards" in auth_client.get(response.url).text


def test_study_anyway(auth_client, course, make_card):
    soon = make_card("Soon", box=4, due_in=timedelta(days=1))
    later = make_card("Later", box=1, due_in=timedelta(days=9))
    auth_client.post(start_url(course), {"mode": "practice"})
    session = StudySession.objects.get()
    assert session.mode == "practice"

    page = auth_client.get(session.get_absolute_url())
    assert "Extra practice" in page.text
    assert page.context["card"] == soon  # the soonest due comes first
    response = answer(auth_client, session, soon, True)
    assert response.context["card"] == later
    response = answer(auth_client, session, later, True)
    assert "Session complete" in response.text


def test_study_anyway_is_capped(auth_client, course, make_card):
    for i in range(PRACTICE_SESSION_CARDS + 5):
        make_card(f"Card {i}", due_in=timedelta(days=3))
    session = start_session(course, mode="practice")
    response = auth_client.get(session.get_absolute_url())
    assert f"Card 1 of {PRACTICE_SESSION_CARDS}" in response.text

    for _ in range(PRACTICE_SESSION_CARDS):
        response = answer(auth_client, session, response.context["card"], True)
    assert "Session complete" in response.text
    assert ReviewLog.objects.count() == PRACTICE_SESSION_CARDS


def test_card_page_has_keyboard_and_accessibility_hooks(auth_client, course, make_card):
    make_card()
    session = start_session(course)
    text = auth_client.get(session.get_absolute_url()).text
    assert '@keydown.window="onKey($event)"' in text
    assert 'role="progressbar"' in text
    assert 'aria-live="polite"' in text
    assert "<kbd>Space</kbd>" in text


# --- Progress ---------------------------------------------------------------------


def test_progress_page(auth_client, course, make_card):
    cards = [make_card(f"Card {i}") for i in range(4)]
    session = start_session(course, now=NOW - timedelta(days=1))
    for card, correct in zip(cards, [True, True, True, False], strict=True):
        record_answer(card, correct, session=session, now=NOW - timedelta(days=1))
    Flashcard.objects.filter(pk=cards[0].pk).update(box=5)

    response = auth_client.get(reverse("study:progress", args=[course.pk]))

    assert response.status_code == 200
    ctx = response.context
    assert [row.count for row in ctx["boxes"]] == [1, 2, 0, 0, 1]
    assert [row.width for row in ctx["boxes"]] == [50, 100, 0, 0, 50]
    assert (ctx["card_count"], ctx["mastered"], ctx["review_count"]) == (4, 1, 4)
    assert ctx["accuracy"] == 75
    assert ctx["streak"] == 1  # studied yesterday, not yet today
    assert [row.accuracy for row in ctx["sessions"]] == [75]
    assert "every 16 days" in response.text
    assert "75%" in response.text


def test_progress_hides_empty_sessions(auth_client, course, make_card):
    make_card()
    start_session(course)
    response = auth_client.get(reverse("study:progress", args=[course.pk]))
    assert response.context["sessions"] == []
    assert "No study sessions yet" in response.text


def test_progress_empty_state_and_privacy(client, auth_client, other_user, course):
    url = reverse("study:progress", args=[course.pk])
    assert "no progress to show" in auth_client.get(url).text
    client.force_login(other_user)
    assert client.get(url).status_code == 404


# --- Stats helpers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("days_ago", "expected"),
    [([], 0), ([0], 1), ([1], 1), ([0, 1, 2], 3), ([1, 2, 3], 3), ([0, 2, 3], 1), ([2, 3], 0)],
)
def test_study_streak(days_ago, expected):
    today = date(2030, 5, 1)
    assert study_streak([today - timedelta(days=d) for d in days_ago], today) == expected


def test_summary_counts_the_top_box_as_neither_up_nor_down(course, make_card):
    top = make_card(box=5)
    session = start_session(course)
    record_answer(top, True, session=session)
    session.refresh_from_db()
    summary = session_summary(session)
    assert (summary.reviewed, summary.promoted, summary.demoted) == (1, 0, 0)
