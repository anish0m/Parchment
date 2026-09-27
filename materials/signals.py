from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Material
from .services import delete_material_file


@receiver(post_delete, sender=Material)
def remove_file_with_material(sender, instance, **kwargs):
    # Also runs when a whole course is deleted and its materials cascade.
    delete_material_file(instance)
