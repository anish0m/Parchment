"""Creating materials and extracting their text.

Extraction runs during the upload request for now. Phase 4 moves it to a
background worker, which is why materials carry a status.
"""

from django.db import transaction

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
    process_material(material)
    return material


def process_material(material):
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
    else:
        material.status = Material.Status.READY

    material.word_count = word_count(material.raw_text)
    material.save()
    return material


def delete_material_file(material):
    """Deletes the stored file once the surrounding transaction commits."""
    if material.file:
        storage, name = material.file.storage, material.file.name
        transaction.on_commit(lambda: storage.delete(name))
