"""Fills a course with sample flashcards, for working on the UI before generation exists."""

import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from courses.models import Course
from flashcards.models import LEITNER_BOXES, Flashcard
from materials.models import Material

SAMPLE_CARDS = {
    "Photosynthesis": [
        ("Where in the cell does photosynthesis happen?", "In the chloroplasts."),
        ("What are the two stages of photosynthesis?", "The light reactions and the Calvin cycle."),
        ("What gas is released by the light reactions?", "Oxygen."),
    ],
    "Cellular respiration": [
        ("Where does most ATP production happen?", "In the mitochondria."),
        ("What is the first stage of cellular respiration?", "Glycolysis, in the cytoplasm."),
        ("What is the final electron acceptor?", "Oxygen, which forms water."),
    ],
    "Cell membrane": [
        ("What is the membrane mainly made of?", "A phospholipid bilayer with proteins."),
        ("What is osmosis?", "Water moving across a membrane towards more solute."),
        ("What does active transport need?", "Energy, usually from ATP."),
    ],
    "Enzymes": [
        ("What do enzymes do?", "Speed up reactions by lowering activation energy."),
        ("What is the active site?", "The region where the substrate binds."),
        ("What happens when an enzyme denatures?", "Its shape changes and it stops working."),
    ],
    "Cell division": [
        ("How many cells does mitosis produce?", "Two genetically identical cells."),
        ("How many cells does meiosis produce?", "Four genetically different gametes."),
    ],
}

NOTES = "\n\n".join(
    f"{concept}\n" + "\n".join(f"{q} {a}" for q, a in cards)
    for concept, cards in SAMPLE_CARDS.items()
)


class Command(BaseCommand):
    help = "Create a course full of sample flashcards for a user."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--course", default="Demo: Cell Biology", help="Course name.")
        parser.add_argument("--count", type=int, default=60, help="Number of cards.")
        parser.add_argument(
            "--reset", action="store_true", help="Delete the course's existing cards first."
        )
        parser.add_argument("--seed", type=int, default=1, help="Random seed.")

    @transaction.atomic
    def handle(self, username, course, count, reset, seed, **options):
        try:
            user = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"No user called {username!r}.") from exc

        rng = random.Random(seed)
        course_obj, _ = Course.objects.get_or_create(owner=user, name=course)
        if reset:
            course_obj.flashcards.all().delete()
        material, _ = Material.objects.get_or_create(
            course=course_obj,
            title="Sample notes",
            defaults={
                "source_type": Material.SourceType.TEXT,
                "raw_text": NOTES,
                "word_count": len(NOTES.split()),
                "status": Material.Status.READY,
            },
        )

        samples = [(c, q, a) for c, cards in SAMPLE_CARDS.items() for q, a in cards]
        now = timezone.now()
        cards = []
        for i in range(count):
            concept, question, answer = samples[i % len(samples)]
            repeat = i // len(samples)
            box = rng.randint(1, LEITNER_BOXES)
            by_hand = rng.random() < 0.2
            cards.append(
                Flashcard(
                    course=course_obj,
                    material=None if by_hand else material,
                    question=question if repeat == 0 else f"{question} (#{repeat + 1})",
                    answer=answer,
                    concept_label="" if by_hand and rng.random() < 0.5 else concept,
                    box=box,
                    next_review_at=now + timedelta(days=rng.randint(-3, 2 ** (box - 1))),
                    is_generated=not by_hand,
                )
            )
        Flashcard.objects.bulk_create(cards)
        self.stdout.write(
            self.style.SUCCESS(f"Added {len(cards)} cards to “{course_obj.name}” for {username}.")
        )
