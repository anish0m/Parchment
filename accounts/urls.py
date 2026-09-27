from django.urls import include, path

from .views import SignUpView

urlpatterns = [
    path("signup/", SignUpView.as_view(), name="signup"),
    # login, logout, password_change*, password_reset*
    path("", include("django.contrib.auth.urls")),
]
