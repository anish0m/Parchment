from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import DeleteView, DetailView, ListView, UpdateView
from django.views.generic.edit import CreateView

from .forms import CourseForm
from .models import Course


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


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


class CourseListView(OwnedCourseMixin, ListView):
    template_name = "courses/course_list.html"
    context_object_name = "courses"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = CourseForm(owner=self.request.user)
        return context


class CourseCreateView(OwnedCourseMixin, CourseFormMixin, CreateView):
    template_name = "courses/course_form.html"

    def form_valid(self, form):
        self.object = form.save()
        if is_htmx(self.request):
            # Return a blank form and refresh the list out of band.
            return render(
                self.request,
                "courses/partials/course_created.html",
                {
                    "form": CourseForm(owner=self.request.user),
                    "courses": self.get_queryset(),
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
            return render(
                self.request,
                "courses/partials/course_list.html",
                {"courses": self.get_queryset()},
            )
        messages.success(self.request, f"Deleted “{name}”.")
        return redirect(self.success_url)
