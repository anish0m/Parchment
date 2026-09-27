from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.CourseListView.as_view(), name="list"),
    path("new/", views.CourseCreateView.as_view(), name="create"),
    path("<int:pk>/", views.CourseDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.CourseUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.CourseDeleteView.as_view(), name="delete"),
]
