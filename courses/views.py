from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Count, Q
from django.db.models.functions import Lower
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import DeleteView, DetailView, ListView, UpdateView
from django.views.generic.edit import CreateView

from flashcards.models import Flashcard
from materials.views import material_list_context
from parchment.htmx import is_htmx, paginate, wants_fragment
from study.views import study_panel_context

from .forms import CourseForm
from .models import Course

COURSES_PER_PAGE = 24


class OwnedCourseMixin(LoginRequiredMixin):
    """Limits every course query to the signed-in user, so other users' courses 404."""

    model = Course

    def get_queryset(self):
        return Course.objects.filter(owner=self.request.user)


class CourseFormMixin:
    form_class = CourseForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["owner"] = self.request.user
        return kwargs


def htmx_redirect(request, url):
    """A full-page redirect, for plain form posts and HTMX (modal) posts alike."""
    if is_htmx(request):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def with_counts(queryset):
    # Aggregating drops the model's default ordering, so order explicitly.
    return queryset.annotate(
        material_count=Count("materials", distinct=True),
        card_count=Count("flashcards", distinct=True),
        due_count=Count(
            "flashcards",
            filter=Q(flashcards__next_review_at__lte=timezone.now()),
            distinct=True,
        ),
        # Joining materials repeats each card equally often, so the average holds.
        box_average=Avg("flashcards__box"),
    ).order_by(Lower("name"))


def course_list_context(queryset, page_number):
    page_obj = paginate(with_counts(queryset), page_number, COURSES_PER_PAGE)
    return {"courses": page_obj.object_list, "page_obj": page_obj}


class CourseListView(OwnedCourseMixin, ListView):
    template_name = "courses/course_list.html"
    context_object_name = "courses"
    paginate_by = COURSES_PER_PAGE

    def get_queryset(self):
        return with_counts(super().get_queryset())

    def get_template_names(self):
        if wants_fragment(self.request, "course-list"):
            return ["courses/partials/course_list.html"]
        return [self.template_name]

    def paginate_queryset(self, queryset, page_size):
        # Out-of-range pages (e.g. after deleting the last course on a page) show
        # the last page instead of a 404.
        page = paginate(queryset, self.request.GET.get("page"), page_size)
        return page.paginator, page, page.object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = CourseForm(owner=self.request.user)
        # "Review across courses": how much is due, and the course with the most.
        due = Flashcard.objects.filter(
            course__owner=self.request.user, next_review_at__lte=timezone.now()
        )
        context["total_due"] = due.count()
        context["due_course_count"] = due.values("course").distinct().count()
        with_due = self.get_queryset().filter(due_count__gt=0)
        context["busiest"] = with_due.order_by("-due_count", Lower("name")).first()
        context["open_modal"] = self.request.GET.get("new") == "1"
        return context


class CourseCreateView(OwnedCourseMixin, CourseFormMixin, CreateView):
    """Creates a course. The modal on the course list and profile posts here with HTMX."""

    template_name = "courses/course_form.html"

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f"Created “{self.object.name}”. Add your first material.")
        return htmx_redirect(self.request, self.object.get_absolute_url())

    def form_invalid(self, form):
        if is_htmx(self.request):
            return render(self.request, "courses/partials/course_form.html", {"form": form})
        return super().form_invalid(form)


class CourseDetailView(OwnedCourseMixin, DetailView):
    template_name = "courses/course_detail.html"
    context_object_name = "course"

    def get_template_names(self):
        if wants_fragment(self.request, "material-list"):
            return ["materials/partials/material_list.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(material_list_context(self.object, self.request.GET.get("page")))
        context.update(study_panel_context(self.object))
        context["course_form"] = CourseForm(instance=self.object, owner=self.request.user)
        return context


class CourseUpdateView(OwnedCourseMixin, CourseFormMixin, UpdateView):
    """Edits a course. The modal on the course page posts here with HTMX."""

    template_name = "courses/course_form.html"
    context_object_name = "course"

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "Course updated.")
        return htmx_redirect(self.request, self.object.get_absolute_url())

    def form_invalid(self, form):
        if is_htmx(self.request):
            return render(
                self.request,
                "courses/partials/course_form.html",
                {"form": form, "editing": self.object},
            )
        return super().form_invalid(form)


class CourseDeleteView(OwnedCourseMixin, DeleteView):
    template_name = "courses/course_confirm_delete.html"
    context_object_name = "course"
    success_url = reverse_lazy("courses:list")

    def form_valid(self, form):
        name = self.object.name
        self.object.delete()
        if is_htmx(self.request):
            # Re-render the page the user was on; if it's now empty, the last page.
            return render(
                self.request,
                "courses/partials/course_list.html",
                course_list_context(self.get_queryset(), self.request.POST.get("page")),
            )
        messages.success(self.request, f"Deleted “{name}”.")
        return redirect(self.success_url)
