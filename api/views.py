from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, parsers, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from courses.models import Course
from courses.views import with_counts
from flashcards.models import Flashcard
from materials.models import Material
from materials.services import AlreadyProcessing, create_material, reprocess
from parchment.throttling import GenerationThrottle, UploadThrottle
from study.models import ReviewLog
from study.scheduler import SessionError, due_cards, record_answer

from .serializers import (
    CourseSerializer,
    FlashcardSerializer,
    MaterialCreateSerializer,
    MaterialDetailSerializer,
    MaterialSerializer,
    ReviewCreateSerializer,
    ReviewResultSerializer,
    ReviewSerializer,
)


def int_param(request, name):
    """An optional whole-number query parameter; anything else is a 400."""
    value = request.query_params.get(name)
    if value in (None, ""):
        return None
    if not value.isdigit():
        raise serializers.ValidationError({name: ["Must be a whole number."]})
    return int(value)


def filter_params(*names, **described):
    return [
        OpenApiParameter(name, OpenApiTypes.INT, description=described.get(name, ""))
        for name in names
    ]


@extend_schema_view(
    list=extend_schema(summary="List your courses"),
    create=extend_schema(summary="Create a course"),
)
class CourseViewSet(viewsets.ModelViewSet):
    serializer_class = CourseSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # building the API schema
            return Course.objects.none()
        return with_counts(Course.objects.filter(owner=self.request.user))

    def perform_create(self, serializer):
        course = serializer.save(owner=self.request.user)
        serializer.instance = self.get_queryset().get(pk=course.pk)  # with its counts

    def perform_update(self, serializer):
        course = serializer.save()
        serializer.instance = self.get_queryset().get(pk=course.pk)

    @extend_schema(
        summary="Cards due now",
        description="Due cards in study order: lowest box first, then the longest overdue.",
        responses=FlashcardSerializer(many=True),
    )
    @action(detail=True)
    def due(self, request, pk=None):
        course = get_object_or_404(Course, pk=pk, owner=request.user)
        page = self.paginate_queryset(due_cards(course))
        return self.get_paginated_response(
            FlashcardSerializer(page, many=True, context=self.get_serializer_context()).data
        )


@extend_schema_view(
    list=extend_schema(
        summary="List your materials", parameters=filter_params("course", course="Course id")
    ),
    retrieve=extend_schema(summary="A material, with its extracted text"),
    create=extend_schema(
        summary="Add a material",
        description=(
            "Paste text (`source_type=text`, `text`) or upload a PDF (`source_type=pdf`, "
            "`file`, as multipart/form-data). Processing and card generation run in the "
            "background: poll the material until `status` is `ready` or `failed`."
        ),
        request=MaterialCreateSerializer,
        responses={201: MaterialDetailSerializer},
    ),
)
class MaterialViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    parser_classes = (parsers.JSONParser, parsers.MultiPartParser, parsers.FormParser)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # building the API schema
            return Material.objects.none()
        materials = Material.objects.filter(course__owner=self.request.user)
        course = int_param(self.request, "course")
        if course is not None:
            materials = materials.filter(course=course)
        return materials.order_by("-created_at", "-pk")

    def get_serializer_class(self):
        if self.action == "create":
            return MaterialCreateSerializer
        if self.action == "list":
            return MaterialSerializer
        return MaterialDetailSerializer

    def get_throttles(self):
        extra = {"create": [UploadThrottle()], "regenerate": [GenerationThrottle()]}
        return super().get_throttles() + extra.get(self.action, [])

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        material = create_material(
            data["course"],
            title=data["title"],
            source_type=data["source_type"],
            text=data["text"],
            upload=data["file"],
        )
        material.refresh_from_db()
        body = MaterialDetailSerializer(material, context=self.get_serializer_context()).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Regenerate a material's cards",
        description=(
            "Replaces generated cards that haven't been edited or reviewed; retries a "
            "material whose processing failed. 409 while it's still being processed."
        ),
        request=None,
        responses={202: MaterialSerializer, 409: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        material = self.get_object()
        try:
            reprocess(material)
        except AlreadyProcessing:
            return Response(
                {"detail": "This material is already being processed."},
                status=status.HTTP_409_CONFLICT,
            )
        material.refresh_from_db()
        return Response(
            MaterialSerializer(material, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )


@extend_schema_view(
    list=extend_schema(
        summary="List your flashcards",
        parameters=[
            *filter_params("course", "material", "box", box="Leitner box, 1 to 5"),
            OpenApiParameter("due", OpenApiTypes.BOOL, description="Only cards due now"),
        ],
    ),
)
class FlashcardViewSet(viewsets.ModelViewSet):
    serializer_class = FlashcardSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # building the API schema
            return Flashcard.objects.none()
        cards = Flashcard.objects.filter(course__owner=self.request.user)
        if self.action != "list":
            return cards
        for name in ("course", "material", "box"):
            value = int_param(self.request, name)
            if value is not None:
                cards = cards.filter(**{name: value})
        if self.request.query_params.get("due") in ("1", "true", "True"):
            cards = cards.filter(next_review_at__lte=timezone.now())
        return cards.order_by("course", "concept_label", "created_at", "pk")

    @extend_schema(
        summary="Answer a card",
        description=(
            "Records a Leitner review: a correct answer moves the card up a box (box 5 "
            "stays in box 5), a wrong one sends it back to box 1, and the card is "
            "rescheduled. Pass `session` to count the answer in a study session."
        ),
        request=ReviewCreateSerializer,
        responses={201: ReviewResultSerializer},
    )
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        card = self.get_object()
        serializer = ReviewCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            log = record_answer(
                card,
                serializer.validated_data["correct"],
                session=serializer.validated_data.get("session"),
            )
        except SessionError as exc:
            raise serializers.ValidationError({"session": [str(exc)]}) from exc
        context = self.get_serializer_context()
        body = {
            "review": ReviewSerializer(log, context=context).data,
            "flashcard": FlashcardSerializer(card, context=context).data,
        }
        return Response(body, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(
        summary="Your review history, newest first",
        parameters=filter_params("course", "flashcard", "session"),
    ),
)
class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReviewSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # building the API schema
            return ReviewLog.objects.none()
        reviews = ReviewLog.objects.filter(user=self.request.user)
        filters = {"course": "flashcard__course", "flashcard": "flashcard", "session": "session"}
        for param, field in filters.items():
            value = int_param(self.request, param)
            if value is not None:
                reviews = reviews.filter(**{field: value})
        return reviews.order_by("-reviewed_at", "-pk")
