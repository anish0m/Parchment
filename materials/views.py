from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DeleteView, DetailView, FormView

from courses.models import Course
from parchment.htmx import is_htmx, paginate

from .forms import MaterialForm
from .models import Material
from .services import create_material

MATERIALS_PER_PAGE = 20


def material_list_context(course, page_number):
    page_obj = paginate(course.materials.all(), page_number, MATERIALS_PER_PAGE)
    return {"course": course, "materials": page_obj.object_list, "page_obj": page_obj}


class OwnedMaterialMixin(LoginRequiredMixin):
    """Limits every material query to the signed-in user's courses, so others' 404."""

    model = Material
    context_object_name = "material"

    def get_queryset(self):
        return Material.objects.filter(course__owner=self.request.user).select_related("course")


class MaterialCreateView(LoginRequiredMixin, FormView):
    form_class = MaterialForm
    template_name = "materials/material_form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.course = get_object_or_404(Course, pk=kwargs["course_pk"], owner=request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["course"] = self.course
        context["max_upload_mb"] = settings.MATERIAL_MAX_UPLOAD_MB
        context["max_pages"] = settings.MATERIAL_MAX_PDF_PAGES
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        material = create_material(
            self.course,
            title=data["title"],
            source_type=data["source_type"],
            text=data["text"],
            upload=data["file"],
        )
        if material.status == Material.Status.READY:
            messages.success(self.request, f"Added “{material.title}”.")
        else:
            messages.error(self.request, f"Couldn't read “{material.title}”.")
        return redirect(material)


class MaterialDetailView(OwnedMaterialMixin, DetailView):
    template_name = "materials/material_detail.html"


class MaterialFileView(OwnedMaterialMixin, View):
    """Serves the original PDF only to the course owner (media files aren't public)."""

    def get(self, request, pk):
        material = get_object_or_404(self.get_queryset(), pk=pk)
        if not material.file:
            raise Http404("This material has no file.")
        try:
            fileobj = material.file.open("rb")
        except FileNotFoundError as exc:
            raise Http404("The file is missing.") from exc
        return FileResponse(
            fileobj,
            content_type="application/pdf",
            filename=material.original_filename or "notes.pdf",
        )


class MaterialDeleteView(OwnedMaterialMixin, DeleteView):
    template_name = "materials/material_confirm_delete.html"

    def form_valid(self, form):
        course, title = self.object.course, self.object.title
        self.object.delete()
        if is_htmx(self.request):
            # Re-render the page the user was on; if it's now empty, the last page.
            return render(
                self.request,
                "materials/partials/material_list.html",
                material_list_context(course, self.request.POST.get("page")),
            )
        messages.success(self.request, f"Deleted “{title}”.")
        return redirect(course)
