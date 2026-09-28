"""Plays out days of Leitner reviews on a course, to see the scheduler at work.

Nothing is kept: the whole run happens in a transaction that is rolled back.
"""

import random
from collections import Counter
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from flashcards.models import LEITNER_BOXES
from study.scheduler import due_cards, end_session, record_answer, start_session


class Command(BaseCommand):
    help = (
        "Simulate a user answering their due cards every day for a while, and print how "
        "the cards move between boxes. Changes are rolled back."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument(
            "--course", help="Course name (default: the user's course with the most cards)."
        )
        parser.add_argument("--days", type=int, default=7, help="Days to simulate (default 7).")
        parser.add_argument(
            "--accuracy",
            type=float,
            default=0.8,
            help="Chance of answering a card correctly, 0 to 1 (default 0.8).",
        )
        parser.add_argument(
            "--per-day", type=int, help="Most cards reviewed a day (default: all due cards)."
        )
        parser.add_argument("--seed", type=int, default=1, help="Random seed.")

    def handle(self, username, course, days, accuracy, per_day, seed, **options):
        if days < 1:
            raise CommandError("--days must be at least 1.")
        if not 0 <= accuracy <= 1:
            raise CommandError("--accuracy must be between 0 and 1.")
        if per_day is not None and per_day < 1:
            raise CommandError("--per-day must be at least 1.")
        try:
            user = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"No user called {username!r}.") from exc

        courses = user.courses.all()
        if course:
            course_obj = courses.filter(name__iexact=course).first()
            if course_obj is None:
                raise CommandError(f"{username} has no course called {course!r}.")
        else:
            course_obj = max(courses, key=lambda c: c.flashcards.count(), default=None)
            if course_obj is None:
                raise CommandError(f"{username} has no courses.")
        if not course_obj.flashcards.exists():
            raise CommandError(f"“{course_obj.name}” has no flashcards to review.")

        rng = random.Random(seed)
        today = timezone.localtime().date()  # study at 9am each day, from today
        with transaction.atomic():
            self._run(course_obj, today, days, accuracy, per_day, rng)
            transaction.set_rollback(True)

    def _boxes(self, course):
        counts = Counter(course.flashcards.values_list("box", flat=True))
        return [counts.get(box, 0) for box in range(1, LEITNER_BOXES + 1)]

    def _line(self, day, date, due, right, missed, boxes):
        cells = f"{day:<4} {date:<11} {due:>4} {right:>6} {missed:>7}  "
        self.stdout.write(cells + "".join(f"{box:>5}" for box in boxes))

    def _run(self, course, today, days, accuracy, per_day, rng):
        self.stdout.write(f"Simulating {days} day(s) of study in “{course.name}”.")
        self.stdout.write(f"Answering {accuracy:.0%} correctly. Nothing will be saved.\n")
        boxes = [f"B{box}" for box in range(1, LEITNER_BOXES + 1)]
        self._line("Day", "Date", "Due", "Right", "Missed", boxes)
        start = self._boxes(course)
        self._line("", "(start)", "", "", "", start)

        total = right = 0
        for day in range(days):
            date = today + timedelta(days=day)
            now = timezone.make_aware(datetime.combine(date, time(9)))
            due = list(due_cards(course, limit=per_day, now=now))
            session = start_session(course, now=now)
            for card in due:
                record_answer(card, rng.random() < accuracy, session=session, now=now)
            end_session(session, now=now)
            session.refresh_from_db()
            total += session.cards_reviewed
            right += session.cards_correct
            missed = session.cards_reviewed - session.cards_correct
            self._line(
                day + 1,
                date.isoformat(),
                len(due),
                session.cards_correct,
                missed,
                self._boxes(course),
            )

        self.stdout.write("")
        if total:
            self.stdout.write(f"{total} reviews, {right / total:.0%} correct.")
        else:
            self.stdout.write("No cards came due.")
        self.stdout.write(self.style.SUCCESS("Simulation finished; all changes rolled back."))
