import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from courses.models import Course
from parchment.htmx import current_query, is_htmx, paginate, wants_fragment

from .forms import CardFilterForm, FlashcardForm
from .models import Flashcard

CARDS_PER_PAGE = 30
FULL_FORM = "flashcards/flashcard_form.html"

# Cards without a concept sort after the named ones.
NO_CONCEPT_LAST = Case(
    When(concept_label="", then=Value(1)), default=Value(0), output_field=IntegerField()
)


def cards_url(course):
    return reverse("flashcards:list", args=[course.pk])


def card_list_context(course, params):
    """Cards for one page of the list, filtered and grouped by concept."""
    filter_form = CardFilterForm(params, course=course)
    cards = (
        filter_form.apply(course.flashcards.select_related("material"))
        # Named concepts alphabetically, cards without a concept last.
        .order_by(
            Case(
                When(concept_label="", then=Value(1)), default=Value(0), output_field=IntegerField()
            ),
            Lower("concept_label"),
            "created_at",
            "pk",
        )
    )
    page_obj = paginate(cards, params.get("page"), CARDS_PER_PAGE)
    return {
        "course": course,
        "filter_form": filter_form,
        "cards": page_obj.object_list,
        "page_obj": page_obj,
        "is_filtered": any(params.get(name) for name in ("material", "box")),
        "materials": course.materials.order_by("title"),
    }


class OwnedCourseView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.course = get_object_or_404(Course, pk=kwargs["course_pk"], owner=request.user)
        return super().dispatch(request, *args, **kwargs)


class OwnedCardView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.card = get_object_or_404(
                Flashcard.objects.select_related("course", "material"),
                pk=kwargs["pk"],
                course__owner=request.user,
            )
        return super().dispatch(request, *args, **kwargs)

    def render_card(self):
        return render(self.request, "flashcards/partials/card.html", {"card": self.card})


class FlashcardListView(OwnedCourseView):
    def get(self, request, course_pk):
        context = card_list_context(self.course, request.GET)
        if wants_fragment(request, "card-list"):
            return render(request, "flashcards/partials/card_list.html", context)
        context["form"] = FlashcardForm(course=self.course)
        return render(request, "flashcards/flashcard_list.html", context)


class FlashcardCreateView(OwnedCourseView):
    def get(self, request, course_pk):
        return redirect(cards_url(self.course))

    def post(self, request, course_pk):
        form = FlashcardForm(request.POST, course=self.course)
        if not form.is_valid():
            template = (
                "flashcards/partials/card_form.html"
                if is_htmx(request)
                else "flashcards/flashcard_form.html"
            )
            return render(request, template, {"form": form, "course": self.course})
        card = form.save()
        if is_htmx(request):
            # A blank form for the next card, and the list refreshed out of band.
            return render(
                request,
                "flashcards/partials/card_created.html",
                {
                    "form": FlashcardForm(course=self.course),
                    "added": card,
                    **card_list_context(self.course, current_query(request)),
                },
            )
        messages.success(request, "Card added.")
        return redirect(cards_url(self.course))


class FlashcardDetailView(OwnedCardView):
    """The card as shown in the list; used by Cancel when editing in place."""

    def get(self, request, pk):
        if is_htmx(request):
            return self.render_card()
        return redirect(cards_url(self.card.course))


class FlashcardUpdateView(OwnedCardView):
    def get(self, request, pk):
        return self.render_form(FlashcardForm(instance=self.card, course=self.card.course))

    def post(self, request, pk):
        form = FlashcardForm(request.POST, instance=self.card, course=self.card.course)
        if not form.is_valid():
            response = self.render_form(form)
            if is_htmx(request):
                # Errors go back into the modal, not into the card's place in the list.
                response["HX-Retarget"] = "#card-edit-modal [data-modal-body]"
                response["HX-Reswap"] = "innerHTML"
            return response
        self.card = form.save()
        if is_htmx(request):
            # The card replaces itself in the list and the edit modal closes.
            response = self.render_card()
            close = {"parchment:close-modal": {"id": "card-edit-modal"}}
            response["HX-Trigger"] = json.dumps(close)
            return response
        messages.success(request, "Card updated.")
        return redirect(cards_url(self.card.course))

    def render_form(self, form):
        template = (
            "flashcards/partials/card_edit.html"
            if is_htmx(self.request)
            else "flashcards/flashcard_form.html"
        )
        return render(
            self.request, template, {"form": form, "card": self.card, "course": self.card.course}
        )


class FlashcardDeleteView(OwnedCardView):
    def get(self, request, pk):
        return render(request, "flashcards/flashcard_confirm_delete.html", {"card": self.card})

    def post(self, request, pk):
        course = self.card.course
        self.card.delete()
        if is_htmx(request):
            # Re-render the list as the user sees it (same filters and page).
            return render(
                request,
                "flashcards/partials/card_list.html",
                card_list_context(course, current_query(request)),
            )
        messages.success(request, "Card deleted.")
        return redirect(cards_url(course))
