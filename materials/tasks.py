"""Background tasks, run by `python manage.py qcluster`."""

import logging

from .models import Material
from .services import extract_material_text

logger = logging.getLogger(__name__)


def process_material(material_id):
    """A new upload: extract its text, then generate its flashcards."""
    material = Material.objects.select_related("course").filter(pk=material_id).first()
    if material is None:  # deleted before the worker got to it
        return
    if extract_material_text(material):
        generate_cards(material)


def regenerate_cards(material_id):
    material = Material.objects.select_related("course").filter(pk=material_id).first()
    if material is not None:
        generate_cards(material)


def generate_cards(material):
    from flashcards.generation.pipeline import PipelineError, generate_flashcards

    material.status = Material.Status.GENERATING
    material.error_message = ""
    material.save(update_fields=["status", "error_message", "updated_at"])
    try:
        result = generate_flashcards(material)
    except PipelineError as exc:
        material.status = Material.Status.FAILED
        material.error_message = str(exc)
    except Exception:
        logger.exception("Card generation failed for material %s", material.pk)
        material.status = Material.Status.FAILED
        material.error_message = (
            "Something went wrong while generating flashcards. Try again, or add cards by hand."
        )
    else:
        material.status = Material.Status.READY
        material.generation_note = result.note
    material.save(update_fields=["status", "error_message", "generation_note", "updated_at"])
