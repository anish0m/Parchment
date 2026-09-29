from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.db.models.functions import Greatest
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView

from courses.forms import CourseForm
from courses.models import Course
from courses.views import with_counts
from materials.models import Material
from parchment.throttling import LoginThrottle, describe_wait, is_blocked, wait_time
from study.models import ReviewLog

from .forms import LoginForm, SignUpForm

LATEST_COURSES = 2


class LoginView(auth_views.LoginView):
    """Django's login, with a limit on failed attempts from one IP address."""

    authentication_form = LoginForm

    def post(self, request, *args, **kwargs):
        wait = is_blocked(request, LoginThrottle)
        if wait:
            messages.error(
                request, f"Too many failed sign-ins. Please try again in {describe_wait(wait)}."
            )
            form = self.get_form_class()(request)
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        wait_time(request=self.request, throttle_class=LoginThrottle)  # count the failure
        return super().form_invalid(form)


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = "registration/signup.html"
    # New accounts start on their profile; logging in goes to the course list.
    success_url = reverse_lazy("profile")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


@login_required
def profile(request):
    user = request.user
    courses = Course.objects.filter(owner=user)
    # "Latest" means the most recent activity: an edit, a new material or a study session.
    latest = (
        with_counts(courses)
        .annotate(
            last_activity=Greatest(
                "updated_at", Max("materials__created_at"), Max("study_sessions__started_at")
            )
        )
        .order_by("-last_activity", "-pk")[:LATEST_COURSES]
    )
    return render(
        request,
        "accounts/profile.html",
        {
            "course_count": courses.count(),
            "material_count": Material.objects.filter(course__owner=user).count(),
            "review_count": ReviewLog.objects.filter(user=user).count(),
            "latest_courses": latest,
            "course_form": CourseForm(owner=user),
        },
    )
