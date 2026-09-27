from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Value
from django.db.models.functions import Lower
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import DeleteView, DetailView, ListView, UpdateView
from django.views.generic.edit import CreateView

from materials.views import material_list_context
from parchment.htmx import is_htmx, paginate, wants_fragment

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


def with_counts(queryset):
    # Aggregating drops the model's default ordering, so order explicitly.
    return queryset.annotate(material_count=Count("materials")).order_by(Lower("name"))


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
        return context


class CourseCreateView(OwnedCourseMixin, CourseFormMixin, CreateView):
    template_name = "courses/course_form.html"

    def form_valid(self, form):
        self.object = form.save()
        if is_htmx(self.request):
            # Return a blank form and refresh the list out of band, on the page
            # where the new course sits in alphabetical order.
            courses = self.get_queryset()
            before = (
                courses.annotate(lower_name=Lower("name"))
                .filter(lower_name__lt=Lower(Value(self.object.name)))
                .count()
            )
            return render(
                self.request,
                "courses/partials/course_created.html",
                {
                    "form": CourseForm(owner=self.request.user),
                    **course_list_context(courses, before // COURSES_PER_PAGE + 1),
                },
            )
        messages.success(self.request, f"Created “{self.object.name}”.")
        return redirect(self.object)

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
        return context


class CourseUpdateView(OwnedCourseMixin, CourseFormMixin, UpdateView):
    template_name = "courses/course_form.html"
    context_object_name = "course"

    def form_valid(self, form):
        messages.success(self.request, "Course updated.")
        return super().form_valid(form)


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
