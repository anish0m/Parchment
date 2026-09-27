from django import forms

from .models import LEITNER_BOXES, Flashcard

MAX_TEXT = 2000


class FlashcardForm(forms.ModelForm):
    question = forms.CharField(max_length=MAX_TEXT, widget=forms.Textarea(attrs={"rows": 2}))
    answer = forms.CharField(max_length=MAX_TEXT, widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = Flashcard
        fields = ("question", "answer", "concept_label", "material")
        widgets = {
            "concept_label": forms.TextInput(attrs={"placeholder": "e.g. Photosynthesis"}),
        }
        help_texts = {"concept_label": "Optional. Cards are grouped by concept."}

    def __init__(self, *args, course, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course
        self.fields["material"].queryset = course.materials.order_by("title")
        self.fields["material"].required = False
        self.fields["material"].empty_label = "None"
        self.fields["material"].label = "From material"

    def clean_concept_label(self):
        return " ".join(self.cleaned_data["concept_label"].split())

    def save(self, commit=True):
        self.instance.course = self.course
        return super().save(commit=commit)


class CardFilterForm(forms.Form):
    """Filters for the card list; invalid values are ignored rather than shown as errors."""

    material = forms.ChoiceField(required=False)
    box = forms.TypedChoiceField(
        coerce=int,
        required=False,
        empty_value=None,
        choices=[("", "All boxes")] + [(b, f"Box {b}") for b in range(1, LEITNER_BOXES + 1)],
    )

    def __init__(self, *args, course, **kwargs):
        # Own ids, so they don't clash with the add-card form on the same page.
        kwargs.setdefault("auto_id", "filter_%s")
        super().__init__(*args, **kwargs)
        self.fields["material"].choices = [("", "All materials"), ("none", "Added by hand")] + [
            (m.pk, m.title) for m in course.materials.order_by("title")
        ]

    def apply(self, queryset):
        if not self.is_valid():
            return queryset
        material = self.cleaned_data.get("material")
        box = self.cleaned_data.get("box")
        if material == "none":
            queryset = queryset.filter(material__isnull=True)
        elif material:
            queryset = queryset.filter(material_id=int(material))
        if box:
            queryset = queryset.filter(box=box)
        return queryset
