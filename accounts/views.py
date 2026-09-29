from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Max
from django.db.models.functions import Greatest
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView

from courses.forms import CourseForm
from courses.models import Course
from courses.views import with_counts
from materials.models import Material
from parchment.throttling import LoginThrottle, describe_wait, is_blocked, wait_time
from study.models import ReviewLog

from .forms import DeleteAccountForm, LoginForm, SignUpForm, UsernameForm

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


@login_required
def account_settings(request):
    """Change what was chosen at sign-up (username, password); the email stays fixed."""
    user = request.user
    username_form = UsernameForm(instance=user, prefix="account")
    password_form = PasswordChangeForm(user, prefix="password")
    action = request.POST.get("action")
    if request.method == "POST" and action == "username":
        username_form = UsernameForm(request.POST, instance=user, prefix="account")
        if username_form.is_valid():
            username_form.save()
            messages.success(request, "Your username has been updated.")
            return redirect("settings")
        # Show the name that's still saved, not the rejected one, in the header.
        user.refresh_from_db(fields=["username"])
    elif request.method == "POST" and action == "password":
        password_form = PasswordChangeForm(user, request.POST, prefix="password")
        if password_form.is_valid():
            password_form.save()
            update_session_auth_hash(request, password_form.user)  # stay signed in
            messages.success(request, "Your password has been changed.")
            return redirect("settings")
    return _render_settings(request, username_form, password_form, DeleteAccountForm(user))


@login_required
@require_POST
def delete_account(request):
    form = DeleteAccountForm(request.user, request.POST)
    if not form.is_valid():
        return _render_settings(
            request,
            UsernameForm(instance=request.user, prefix="account"),
            PasswordChangeForm(request.user, prefix="password"),
            form,
            open_delete=True,
        )
    user = request.user
    logout(request)
    user.delete()  # courses, materials, cards and study history go with it
    messages.success(request, "Your account and everything in it has been deleted.")
    return redirect("home")


def _render_settings(request, username_form, password_form, delete_form, open_delete=False):
    status = (
        400
        if any(f.is_bound and f.errors for f in (username_form, password_form, delete_form))
        else 200
    )
    return render(
        request,
        "accounts/settings.html",
        {
            "username_form": username_form,
            "password_form": password_form,
            "delete_form": delete_form,
            "open_delete": open_delete,
        },
        status=status,
    )
