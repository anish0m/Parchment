from django.contrib import admin
from django.urls import include, path

from . import views

# Uploaded files (MEDIA_ROOT) are deliberately not served at a public URL;
# materials.views.MaterialFileView serves each PDF to its owner only.
urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("accounts/", include("accounts.urls")),
    path("courses/", include("courses.urls")),
    path("", include("materials.urls")),
    path("", include("flashcards.urls")),
    path("", include("study.urls")),
    path("api/", include("api.urls")),
    path("admin/", admin.site.urls),
]
