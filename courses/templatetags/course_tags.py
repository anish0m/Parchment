from django import template

from flashcards.models import LEITNER_BOXES

register = template.Library()


@register.filter
def mastery(box_average):
    """How far a course's cards have climbed the Leitner boxes, 0 to 100.

    0 when every card is in box 1, 100 when every card is in the top box.
    """
    if box_average is None:
        return 0
    return round((float(box_average) - 1) / (LEITNER_BOXES - 1) * 100)


@register.filter
def initial(name):
    """The first letter or digit of a name, for course and profile icons."""
    for char in str(name):
        if char.isalnum():
            return char.upper()
    return "✦"
