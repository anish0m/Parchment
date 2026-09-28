from django.db.models.functions import Lower
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from courses.models import Course
from flashcards.forms import MAX_TEXT
from flashcards.models import Flashcard
from materials.forms import MaterialForm
from materials.models import Material
from study.models import ReviewLog, StudySession


def _owned_courses(serializer):
    return Course.objects.filter(owner=serializer.context["request"].user)


@extend_schema_field(OpenApiTypes.INT)
class OwnedCourseField(serializers.PrimaryKeyRelatedField):
    """A course id; only the signed-in user's courses are accepted."""

    def get_queryset(self):
        return _owned_courses(self.parent)


@extend_schema_field(OpenApiTypes.INT)
class OwnedMaterialField(serializers.PrimaryKeyRelatedField):
    """A material id from one of the signed-in user's courses."""

    def get_queryset(self):
        return Material.objects.filter(course__owner=self.parent.context["request"].user)


class CourseSerializer(serializers.ModelSerializer):
    material_count = serializers.IntegerField(read_only=True)
    card_count = serializers.IntegerField(read_only=True)
    due_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Course
        fields = (
            "id",
            "name",
            "description",
            "material_count",
            "card_count",
            "due_count",
            "created_at",
            "updated_at",
        )

    def validate_name(self, name):
        name = " ".join(name.split())
        if not name:
            raise serializers.ValidationError("A course needs a name.")
        others = _owned_courses(self).annotate(lower=Lower("name")).filter(lower=name.lower())
        if self.instance:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise serializers.ValidationError("You already have a course with this name.")
        return name


class MaterialSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = (
            "id",
            "course",
            "title",
            "source_type",
            "status",
            "status_display",
            "error_message",
            "generation_note",
            "original_filename",
            "file_url",
            "page_count",
            "word_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_file_url(self, material) -> str | None:
        if not material.file:
            return None
        url = reverse("materials:file", args=[material.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class MaterialDetailSerializer(MaterialSerializer):
    class Meta(MaterialSerializer.Meta):
        fields = (*MaterialSerializer.Meta.fields, "raw_text")
        read_only_fields = fields


class MaterialCreateSerializer(serializers.Serializer):
    """Pasted text (JSON or form data) or a PDF (multipart), checked like the web form."""

    course = OwnedCourseField()
    source_type = serializers.ChoiceField(choices=Material.SourceType.choices)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    file = serializers.FileField(required=False, allow_null=True)

    def validate(self, attrs):
        form = MaterialForm(
            data={
                "source_type": attrs["source_type"],
                "title": attrs.get("title", ""),
                "text": attrs.get("text", ""),
            },
            files={"file": attrs["file"]} if attrs.get("file") else {},
        )
        if not form.is_valid():
            errors = form.errors.get_json_data()
            raise serializers.ValidationError(
                {
                    ("non_field_errors" if field == "__all__" else field): [
                        e["message"] for e in field_errors
                    ]
                    for field, field_errors in errors.items()
                }
            )
        return {"course": attrs["course"], **form.cleaned_data}


class FlashcardSerializer(serializers.ModelSerializer):
    course = OwnedCourseField()
    material = OwnedMaterialField(required=False, allow_null=True)
    question = serializers.CharField(max_length=MAX_TEXT)
    answer = serializers.CharField(max_length=MAX_TEXT)

    class Meta:
        model = Flashcard
        fields = (
            "id",
            "course",
            "material",
            "question",
            "answer",
            "concept_label",
            "source_excerpt",
            "box",
            "next_review_at",
            "is_generated",
            "is_edited",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "source_excerpt",
            "box",
            "next_review_at",
            "is_generated",
            "is_edited",
            "created_at",
            "updated_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(self.instance, Flashcard):
            # A card stays in its course; move it by making a new one.
            self.fields["course"].read_only = True

    def validate_concept_label(self, label):
        return " ".join(label.split())

    def validate(self, attrs):
        course = attrs.get("course") or getattr(self.instance, "course", None)
        material = attrs.get("material")
        if material is not None and material.course_id != course.pk:
            raise serializers.ValidationError(
                {"material": ["This material belongs to a different course."]}
            )
        return attrs

    def update(self, instance, validated_data):
        changed = any(getattr(instance, k) != v for k, v in validated_data.items())
        if changed:
            instance.is_edited = True
        return super().update(instance, validated_data)


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewLog
        fields = (
            "id",
            "flashcard",
            "session",
            "was_correct",
            "box_before",
            "box_after",
            "reviewed_at",
        )
        read_only_fields = fields


class ReviewCreateSerializer(serializers.Serializer):
    correct = serializers.BooleanField()
    session = serializers.PrimaryKeyRelatedField(
        queryset=StudySession.objects.none(), required=False, allow_null=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request:
            self.fields["session"].queryset = StudySession.objects.filter(user=request.user)


class ReviewResultSerializer(serializers.Serializer):
    review = ReviewSerializer()
    flashcard = FlashcardSerializer()
