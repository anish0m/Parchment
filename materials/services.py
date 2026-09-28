"""Creating materials, and the text-extraction step of processing them.

Processing runs in a background worker (materials.tasks); with Q_CLUSTER["sync"]
it runs inline instead, which the tests use.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .extraction import ExtractionError, extract_pdf_text
from .models import Material
from .text_cleaning import clean_pasted_text, word_count


def create_material(course, *, title, source_type, text="", upload=None):
    material = Material(course=course, title=title, source_type=source_type)
    if source_type == Material.SourceType.PDF:
        material.original_filename = upload.name[:255]
        material.file.save(upload.name, upload, save=False)
    else:
        material.raw_text = text
    material.save()
    enqueue("materials.tasks.process_material", material)
    return material


class AlreadyProcessing(Exception):
    """The material is being processed right now, so it can't be restarted."""


def is_stalled(material):
    """Still "in progress" long after a worker would have finished or timed out."""
    limit = timedelta(seconds=settings.Q_CLUSTER["timeout"] + 300)
    return material.in_progress and timezone.now() - material.updated_at > limit


def reprocess(material):
    """Regenerate a material's cards, or retry one whose processing failed or stalled.

    Returns "regenerate" or "process" (the step that was queued). Raises
    AlreadyProcessing while a worker is still on it.
    """
    if material.in_progress and not is_stalled(material):
        raise AlreadyProcessing
    material.status = Material.Status.PENDING
    material.error_message = ""
    material.save(update_fields=["status", "error_message", "updated_at"])
    if material.raw_text:
        enqueue("materials.tasks.regenerate_cards", material)
        return "regenerate"
    enqueue("materials.tasks.process_material", material)
    return "process"


def enqueue(task, material):
    """Queues a task for a material once the current transaction has committed."""
    from django_q.tasks import async_task

    def send():
        async_task(task, material.pk, group="materials", task_name=f"{task}:{material.pk}")

    if settings.Q_CLUSTER.get("sync"):
        send()
    else:
        transaction.on_commit(send)


def extract_material_text(material):
    """Fills in the material's text. Returns False (and marks it failed) if it can't."""
    material.status = Material.Status.PROCESSING
    material.error_message = ""
    material.save(update_fields=["status", "error_message", "updated_at"])

    try:
        if material.is_pdf:
            with material.file.open("rb") as fileobj:
                result = extract_pdf_text(fileobj)
            material.raw_text = result.text
            material.page_count = result.page_count
        else:
            material.raw_text = clean_pasted_text(material.raw_text)
    except ExtractionError as exc:
        material.status = Material.Status.FAILED
        material.error_message = str(exc)
        material.raw_text = ""
    material.word_count = word_count(material.raw_text)
    material.save()
    return material.status != Material.Status.FAILED


def delete_material_file(material):
    """Deletes the stored file once the surrounding transaction commits."""
    if material.file:
        storage, name = material.file.storage, material.file.name
        transaction.on_commit(lambda: storage.delete(name))
