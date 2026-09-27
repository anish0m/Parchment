from django import forms

from .models import Course


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ("name", "description")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Organic Chemistry"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_name(self):
        # The owner isn't a form field, so the model's unique constraint isn't
        # checked by form validation. Check it here to show a field error
        # instead of a database IntegrityError.
        name = self.cleaned_data["name"].strip()
        duplicates = Course.objects.filter(owner=self.owner, name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("You already have a course with this name.")
        return name

    def save(self, commit=True):
        self.instance.owner = self.owner
        return super().save(commit=commit)
