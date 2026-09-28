from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.checks import run_checks
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from flashcards.models import LEITNER_BOXES, Flashcard
from study.models import ReviewLog, StudySession
from study.scheduler import (
    SessionError,
    due_cards,
    end_session,
    interval_for,
    next_box,
    next_review_time,
    record_answer,
    start_session,
)

UTC = ZoneInfo("UTC")
# A fixed "now" for every test that needs a clock: Wednesday 1 May 2030, 15:30 UTC.
NOW = datetime(2030, 5, 1, 15, 30, tzinfo=UTC)
MIDNIGHT = datetime(2030, 5, 1, tzinfo=UTC)


@pytest.fixture
def course(user, make_course):
    return make_course(user)


@pytest.fixture
def make_card(course):
    def make(question="What is osmosis?", **kwargs):
        kwargs.setdefault("next_review_at", NOW - timedelta(minutes=1))
        return Flashcard.objects.create(course=course, question=question, answer="A.", **kwargs)

    return make


@pytest.fixture
def frozen(monkeypatch):
    """Freeze timezone.now() at NOW for code that doesn't take a `now` argument."""
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    return NOW


# --- Box moves and intervals ------------------------------------------------------


@pytest.mark.parametrize(
    ("box", "correct", "expected"),
    [
        (1, True, 2),
        (2, True, 3),
        (4, True, 5),
        (5, True, 5),
        (1, False, 1),
        (3, False, 1),
        (5, False, 1),
    ],
)
def test_next_box(box, correct, expected):
    assert next_box(box, correct) == expected


def test_default_intervals_double_each_box(settings):
    assert settings.LEITNER_INTERVAL_DAYS == [1, 2, 4, 8, 16]
    assert [interval_for(box).days for box in range(1, LEITNER_BOXES + 1)] == [1, 2, 4, 8, 16]


@pytest.mark.parametrize("box", [0, LEITNER_BOXES + 1])
def test_interval_rejects_boxes_out_of_range(box):
    with pytest.raises(ValueError):
        interval_for(box)


def test_intervals_come_from_settings(settings):
    settings.LEITNER_INTERVAL_DAYS = [1, 3, 7, 14, 30]
    assert next_review_time(5, NOW) == MIDNIGHT + timedelta(days=30)


@pytest.mark.parametrize("box", range(1, LEITNER_BOXES + 1))
def test_next_review_is_midnight_interval_days_later(box):
    expected = MIDNIGHT + timedelta(days=2 ** (box - 1))
    assert next_review_time(box, NOW) == expected
    # Answering just after midnight or just before the next one gives the same day.
    assert next_review_time(box, MIDNIGHT) == expected
    assert next_review_time(box, MIDNIGHT + timedelta(hours=23, minutes=59)) == expected


def test_next_review_uses_the_local_day():
    # 01:30 on 2 May in Dhaka is still 1 May in UTC; tomorrow means 3 May, Dhaka time.
    dhaka = ZoneInfo("Asia/Dhaka")
    with timezone.override(dhaka):
        due = next_review_time(1, datetime(2030, 5, 1, 19, 30, tzinfo=UTC))
    assert due == datetime(2030, 5, 3, tzinfo=dhaka)


def test_next_review_uses_now_by_default(frozen):
    assert next_review_time(1) == MIDNIGHT + timedelta(days=1)


# --- record_answer ----------------------------------------------------------------


def test_correct_answer_promotes_and_logs(make_card, user):
    card = make_card(box=2)

    log = record_answer(card, correct=True, now=NOW)

    assert (card.box, card.next_review_at) == (3, MIDNIGHT + timedelta(days=4))
    card.refresh_from_db()
    assert (card.box, card.next_review_at) == (3, MIDNIGHT + timedelta(days=4))
    assert (log.flashcard, log.user, log.session) == (card, user, None)
    assert (log.was_correct, log.box_before, log.box_after) == (True, 2, 3)
    assert log.reviewed_at == NOW
    assert log.was_promoted and not log.was_demoted


def test_wrong_answer_sends_the_card_back_to_box_one(make_card):
    card = make_card(box=4)

    log = record_answer(card, correct=False, now=NOW)

    card.refresh_from_db()
    assert (card.box, card.next_review_at) == (1, MIDNIGHT + timedelta(days=1))
    assert (log.was_correct, log.box_before, log.box_after) == (False, 4, 1)
    assert log.was_demoted


def test_top_box_is_a_cap(make_card):
    card = make_card(box=LEITNER_BOXES)

    log = record_answer(card, correct=True, now=NOW)

    assert card.box == LEITNER_BOXES
    assert card.next_review_at == MIDNIGHT + timedelta(days=16)
    assert not log.was_promoted and not log.was_demoted


def test_wrong_answer_in_box_one_stays_in_box_one(make_card):
    card = make_card(box=1)
    record_answer(card, correct=False, now=NOW)
    assert card.box == 1
    assert card.next_review_at == MIDNIGHT + timedelta(days=1)


def test_record_answer_uses_now_by_default(make_card, frozen):
    card = make_card()
    log = record_answer(card, correct=True)
    assert log.reviewed_at == NOW
    assert card.next_review_at == MIDNIGHT + timedelta(days=2)


def test_answer_reads_the_current_box_not_a_stale_copy(make_card):
    card = make_card(box=1)
    stale = Flashcard.objects.get(pk=card.pk)
    record_answer(card, correct=True, now=NOW)

    log = record_answer(stale, correct=True, now=NOW)

    assert (log.box_before, log.box_after) == (2, 3)
    assert stale.box == 3


def test_a_failed_log_rolls_back_the_card(make_card, monkeypatch):
    card = make_card(box=2)

    def broken(**kwargs):
        raise IntegrityError("log failed")

    monkeypatch.setattr(ReviewLog.objects, "create", broken)
    with pytest.raises(IntegrityError):
        record_answer(card, correct=True, now=NOW)

    card.refresh_from_db()
    assert card.box == 2
    assert card.next_review_at < NOW


def test_a_week_of_answers(make_card):
    """Box 1 → 5 over the scheduled days, then one miss sends it back."""
    card = make_card(next_review_at=MIDNIGHT)
    day = NOW
    seen = []
    for _ in range(LEITNER_BOXES):
        assert due_cards(card.course, now=day).get() == card
        record_answer(card, correct=True, now=day)
        assert not due_cards(card.course, now=day).exists()
        # The day before it's due, it isn't; on the due day, it is.
        assert not due_cards(card.course, now=card.next_review_at - timedelta(seconds=1))
        seen.append((card.box, (card.next_review_at - MIDNIGHT).days))
        day = card.next_review_at + timedelta(hours=9)

    assert seen == [(2, 2), (3, 6), (4, 14), (5, 30), (5, 46)]
    record_answer(card, correct=False, now=day)
    assert card.box == 1
    assert list(card.reviews.values_list("box_after", flat=True)) == [1, 5, 5, 4, 3, 2]


# --- Due cards --------------------------------------------------------------------


def test_due_cards_order_and_cutoff(make_card, course):
    later = make_card("Not due yet", next_review_at=NOW + timedelta(seconds=1))
    box3_old = make_card("Box 3, overdue", box=3, next_review_at=NOW - timedelta(days=5))
    box1_recent = make_card("Box 1, just due", box=1, next_review_at=NOW)
    box1_old = make_card("Box 1, overdue", box=1, next_review_at=NOW - timedelta(days=2))
    box2 = make_card("Box 2", box=2, next_review_at=NOW - timedelta(days=9))

    due = list(due_cards(course, now=NOW))

    assert due == [box1_old, box1_recent, box2, box3_old]
    assert later not in due
    assert list(due_cards(course, limit=2, now=NOW)) == [box1_old, box1_recent]


def test_ties_are_broken_by_creation_order(make_card, course):
    cards = [make_card(f"Card {i}", next_review_at=MIDNIGHT) for i in range(3)]
    assert list(due_cards(course, now=NOW)) == cards


def test_new_cards_are_due_straight_away(course):
    card = Flashcard.objects.create(course=course, question="New?", answer="Yes.")
    assert list(due_cards(course)) == [card]


def test_due_cards_are_limited_to_the_course(make_card, user, other_user, make_course):
    mine = make_card()
    other_course = make_course(other_user, "Someone else's")
    Flashcard.objects.create(
        course=other_course, question="Theirs?", answer="A.", next_review_at=NOW - timedelta(1)
    )
    assert list(due_cards(mine.course, now=NOW)) == [mine]


def test_due_cards_query_count(make_card, course, django_assert_num_queries):
    for i in range(5):
        make_card(f"Card {i}")
    with django_assert_num_queries(1):
        assert len(list(due_cards(course, now=NOW))) == 5


# --- Sessions ---------------------------------------------------------------------


def test_session_counts_answers(make_card, course, user):
    session = start_session(course, now=NOW)
    assert (session.user, session.course, session.started_at) == (user, course, NOW)
    assert session.is_active and session.accuracy is None

    for i, correct in enumerate([True, False, True, True]):
        record_answer(make_card(f"Card {i}"), correct, session=session, now=NOW)

    session.refresh_from_db()
    assert (session.cards_reviewed, session.cards_correct) == (4, 3)
    assert session.accuracy == 0.75
    assert session.reviews.count() == 4


def test_ending_a_session_is_idempotent(course):
    session = start_session(course, now=NOW)
    end_session(session, now=NOW + timedelta(minutes=5))
    end_session(session, now=NOW + timedelta(hours=1))
    session.refresh_from_db()
    assert session.ended_at == NOW + timedelta(minutes=5)
    assert not session.is_active


def test_ended_session_refuses_answers(make_card, course):
    card = make_card(box=2)
    session = end_session(start_session(course, now=NOW), now=NOW)

    with pytest.raises(SessionError):
        record_answer(card, correct=True, session=session, now=NOW)

    card.refresh_from_db()
    assert card.box == 2
    assert not ReviewLog.objects.exists()


def test_session_refuses_cards_from_another_course(make_card, user, make_course):
    card = make_card()
    session = start_session(make_course(user, "Chemistry"), now=NOW)
    with pytest.raises(SessionError):
        record_answer(card, correct=True, session=session, now=NOW)
    assert not ReviewLog.objects.exists()


def test_deleting_a_session_keeps_its_reviews(make_card, course):
    session = start_session(course, now=NOW)
    log = record_answer(make_card(), correct=True, session=session, now=NOW)
    session.delete()
    log.refresh_from_db()
    assert log.session is None


def test_deleting_a_card_or_course_deletes_its_history(make_card, course):
    card = make_card()
    start = start_session(course, now=NOW)
    record_answer(card, correct=True, session=start, now=NOW)
    card.delete()
    assert not ReviewLog.objects.exists()

    course.delete()
    assert not StudySession.objects.exists()


def test_database_rejects_impossible_rows(make_card, course, user):
    card = make_card()
    with transaction.atomic(), pytest.raises(IntegrityError):
        ReviewLog.objects.create(
            flashcard=card, user=user, was_correct=True, box_before=5, box_after=6
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        StudySession.objects.create(user=user, course=course, cards_reviewed=1, cards_correct=2)


# --- Settings check ---------------------------------------------------------------


@pytest.mark.parametrize(
    "intervals",
    [
        [1, 2, 4, 8],
        [1, 2, 4, 8, 16, 32],
        [0, 2, 4, 8, 16],
        [1, 2, 8, 4, 16],
        [1, 2, 4, 8, 1.5],
        "1,2,4,8,16",
    ],
)
def test_bad_intervals_fail_the_system_check(settings, intervals):
    settings.LEITNER_INTERVAL_DAYS = intervals
    assert "study.E001" in {error.id for error in run_checks()}


def test_default_intervals_pass_the_system_check():
    assert "study.E001" not in {error.id for error in run_checks()}


# --- simulate_reviews -------------------------------------------------------------


def day_rows(out):
    """The per-day rows of the command's table, split into cells."""
    return [
        row
        for line in out.splitlines()
        if len(row := line.split()) == 5 + LEITNER_BOXES and row[0].isdigit()
    ]


def test_simulate_reviews_prints_each_day_and_rolls_back(make_card, user, capsys, frozen):
    cards = [make_card(f"Card {i}", next_review_at=MIDNIGHT) for i in range(6)]

    call_command("simulate_reviews", user.username, "--days", "7", "--accuracy", "1")

    out = capsys.readouterr().out
    rows = day_rows(out)
    assert [row[0] for row in rows] == [str(day) for day in range(1, 8)]
    # All correct: every card is due on days 1, 3 and 7 (after 2 then 4 days).
    assert [int(row[2]) for row in rows] == [6, 0, 6, 0, 0, 0, 6]
    assert rows[-1][-LEITNER_BOXES:] == ["0", "0", "0", "6", "0"]
    assert "18 reviews, 100% correct." in out
    # Nothing was saved.
    assert not ReviewLog.objects.exists() and not StudySession.objects.exists()
    assert {c.box for c in Flashcard.objects.filter(pk__in=[c.pk for c in cards])} == {1}


def test_simulate_reviews_with_misses_and_a_daily_limit(make_card, user, capsys, frozen):
    for i in range(10):
        make_card(f"Card {i}", next_review_at=MIDNIGHT)

    call_command(
        "simulate_reviews", user.username, "--days", "3", "--accuracy", "0", "--per-day", "4"
    )

    out = capsys.readouterr().out
    rows = day_rows(out)
    # Every answer is wrong, so each day's 4 reviews stay in box 1.
    assert [row[2:5] for row in rows] == [["4", "0", "4"]] * 3
    assert "12 reviews, 0% correct." in out


def test_simulate_reviews_picks_a_course(make_card, user, make_course, capsys):
    make_card()
    make_course(user, "Empty course")
    call_command("simulate_reviews", user.username, "--days", "1")
    assert "Biology 101" in capsys.readouterr().out
    with pytest.raises(CommandError, match="no flashcards"):
        call_command("simulate_reviews", user.username, "--course", "empty COURSE")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["nobody"], "No user"),
        (["alice", "--course", "Nope"], "no course"),
        (["alice", "--days", "0"], "--days"),
        (["alice", "--accuracy", "1.5"], "--accuracy"),
        (["alice", "--per-day", "0"], "--per-day"),
    ],
)
def test_simulate_reviews_errors(user, args, message):
    with pytest.raises(CommandError, match=message):
        call_command("simulate_reviews", *args)


def test_simulate_reviews_needs_a_course(user):
    with pytest.raises(CommandError, match="no courses"):
        call_command("simulate_reviews", user.username)
