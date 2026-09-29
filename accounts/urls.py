from django.urls import include, path
from django.views.generic import RedirectView

from .views import LoginView, SignUpView, account_settings, delete_account, profile

urlpatterns = [
    path("signup/", SignUpView.as_view(), name="signup"),
    path("login/", LoginView.as_view(), name="login"),
    path("profile/", profile, name="profile"),
    path("settings/", account_settings, name="settings"),
    path("settings/delete/", delete_account, name="delete_account"),
    # Passwords are changed in settings now; old links land there.
    path(
        "password_change/",
        RedirectView.as_view(pattern_name="settings", permanent=False),
        name="password_change",
    ),
    path(
        "password_change/done/",
        RedirectView.as_view(pattern_name="settings", permanent=False),
        name="password_change_done",
    ),
    # login, logout, password_reset*
    path("", include("django.contrib.auth.urls")),
]
