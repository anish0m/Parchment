from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from parchment.throttling import LoginThrottle, describe_wait, is_blocked, wait_time

from .forms import SignUpForm


class LoginView(auth_views.LoginView):
    """Django's login, with a limit on failed attempts from one IP address."""

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
    success_url = reverse_lazy(settings.LOGIN_REDIRECT_URL)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response
