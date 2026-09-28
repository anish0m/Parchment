from django.urls import path

from . import views

app_name = "materials"

urlpatterns = [
    path(
        "courses/<int:course_pk>/materials/new/",
        views.MaterialCreateView.as_view(),
        name="create",
    ),
    path("materials/<int:pk>/", views.MaterialDetailView.as_view(), name="detail"),
    path("materials/<int:pk>/file/", views.MaterialFileView.as_view(), name="file"),
    path("materials/<int:pk>/delete/", views.MaterialDeleteView.as_view(), name="delete"),
    path("materials/<int:pk>/status/", views.MaterialStatusView.as_view(), name="status"),
    path(
        "materials/<int:pk>/regenerate/",
        views.MaterialRegenerateView.as_view(),
        name="regenerate",
    ),
]
