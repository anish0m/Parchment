from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DeleteView, DetailView, FormView

from courses.models import Course
from parchment.htmx import current_query, is_htmx, paginate
from parchment.throttling import GenerationThrottle, UploadThrottle, describe_wait, wait_time

from .forms import MaterialForm
from .models import Material
from .services import AlreadyProcessing, create_material, is_stalled, reprocess

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
        wait = wait_time(self.request, UploadThrottle)
        if wait:
            form.add_error(
                None,
                "You've added a lot of materials in a short time. "
                f"Please try again in {describe_wait(wait)}.",
            )
            return self.form_invalid(form)
        data = form.cleaned_data
        material = create_material(
            self.course,
            title=data["title"],
            source_type=data["source_type"],
            text=data["text"],
            upload=data["file"],
        )
        material.refresh_from_db()
        if material.status == Material.Status.FAILED:
            messages.error(self.request, f"Couldn't process “{material.title}”.")
        elif material.in_progress:
            messages.success(
                self.request,
                f"Added “{material.title}”. Its flashcards are being generated; "
                "this page updates when they're ready.",
            )
        else:
            messages.success(self.request, f"Added “{material.title}”.")
        return redirect(material)


class MaterialDetailView(OwnedMaterialMixin, DetailView):
    template_name = "materials/material_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        material = self.object
        context["card_count"] = material.flashcards.count()
        context["stalled"] = is_stalled(material)
        context["cards_url"] = (
            reverse("flashcards:list", args=[material.course_id]) + f"?material={material.pk}"
        )
        return context


class MaterialStatusView(OwnedMaterialMixin, View):
    """Polled by HTMX while a material is processing.

    ?view=row returns the material's row for the course page; otherwise the status
    badge for its own page, which reloads once processing has finished.
    """

    def get(self, request, pk):
        material = get_object_or_404(self.get_queryset(), pk=pk)
        if request.GET.get("view") == "row":
            return render(request, "materials/partials/material_row.html", {"material": material})
        response = render(request, "materials/partials/detail_status.html", {"material": material})
        if not material.in_progress:
            response["HX-Refresh"] = "true"  # show the results
        return response


class MaterialRegenerateView(OwnedMaterialMixin, View):
    """Regenerates cards, or retries a material whose processing failed or stalled."""

    def post(self, request, pk):
        material = get_object_or_404(self.get_queryset(), pk=pk)
        wait = wait_time(request, GenerationThrottle)
        if wait:
            messages.error(
                request,
                "You've regenerated cards a lot in a short time. "
                f"Please try again in {describe_wait(wait)}.",
            )
            return redirect(material)
        try:
            step = reprocess(material)
        except AlreadyProcessing:
            messages.info(request, "This material is already being processed.")
            return redirect(material)
        if step == "regenerate":
            messages.success(request, "Generating new flashcards…")
        else:
            messages.success(request, "Processing this material again…")
        return redirect(material)


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
                material_list_context(
                    course,
                    current_query(self.request).get("page") or self.request.POST.get("page"),
                ),
            )
        messages.success(self.request, f"Deleted “{title}”.")
        return redirect(course)
