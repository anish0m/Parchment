from django.urls import include, path

from .views import LoginView, SignUpView

urlpatterns = [
    path("signup/", SignUpView.as_view(), name="signup"),
    path("login/", LoginView.as_view(), name="login"),
    # login, logout, password_change*, password_reset*
    path("", include("django.contrib.auth.urls")),
]
