from pathlib import Path

from django import forms
from django.conf import settings
from django.template.defaultfilters import filesizeformat

from .models import Material

# The PDF spec allows the header anywhere in the first 1024 bytes.
PDF_HEADER_WINDOW = 1024


class MaterialForm(forms.Form):
    source_type = forms.ChoiceField(
        choices=Material.SourceType.choices,
        initial=Material.SourceType.PDF,
        # x-model lets Alpine show the text box or the file picker to match.
        # Chosen with tabs in the template (a hidden input).
        widget=forms.HiddenInput,
        label="Add notes as",
    )
    title = forms.CharField(
        max_length=200,
        required=False,
        help_text="Optional. Defaults to the file name or the first line of the text.",
        widget=forms.TextInput(attrs={"placeholder": "Material title"}),
    )
    text = forms.CharField(
        required=False,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 10, "placeholder": "Paste your notes here…"}),
        label="Notes",
    )
    file = forms.FileField(
        required=False,
        label="PDF file",
        widget=forms.FileInput(attrs={"accept": ".pdf,application/pdf", "data-file-input": ""}),
    )

    def clean_text(self):
        text = self.cleaned_data["text"]
        limit = settings.MATERIAL_MAX_TEXT_CHARS
        if len(text) > limit:
            raise forms.ValidationError(
                f"That's {len(text):,} characters; the limit is {limit:,}. "
                "Split it into several materials."
            )
        return text

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if not upload:
            return upload
        if Path(upload.name).suffix.lower() != ".pdf":
            raise forms.ValidationError("Only PDF files can be uploaded.")
        if upload.size == 0:
            raise forms.ValidationError("This file is empty.")
        limit = settings.MATERIAL_MAX_UPLOAD_MB * 1024 * 1024
        if upload.size > limit:
            raise forms.ValidationError(
                f"This file is {filesizeformat(upload.size)}; the limit is {filesizeformat(limit)}."
            )
        head = upload.read(PDF_HEADER_WINDOW)
        upload.seek(0)
        if b"%PDF-" not in head:
            raise forms.ValidationError("This file isn't a valid PDF.")
        return upload

    def clean(self):
        cleaned = super().clean()
        source_type = cleaned.get("source_type")
        if source_type == Material.SourceType.TEXT:
            if not cleaned.get("text") and "text" not in self.errors:
                self.add_error("text", "Paste some notes, or switch to uploading a PDF.")
        elif source_type == Material.SourceType.PDF:
            if not cleaned.get("file") and "file" not in self.errors:
                self.add_error("file", "Choose a PDF to upload, or switch to pasting text.")

        if not self.errors and not cleaned.get("title"):
            cleaned["title"] = self._default_title(cleaned)
        return cleaned

    @staticmethod
    def _default_title(cleaned):
        if cleaned["source_type"] == Material.SourceType.PDF:
            title = Path(cleaned["file"].name).stem.replace("_", " ").strip()
        else:
            first_line = next(
                (line.strip() for line in cleaned["text"].splitlines() if line.strip()), ""
            )
            title = first_line
        title = title or "Untitled notes"
        return title if len(title) <= 80 else title[:79].rstrip() + "…"
