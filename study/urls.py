from django.urls import path

from . import views

app_name = "study"

urlpatterns = [
    path("courses/<int:course_pk>/study/", views.start, name="start"),
    path("courses/<int:course_pk>/study/panel/", views.study_panel, name="panel"),
    path("courses/<int:course_pk>/progress/", views.progress, name="progress"),
    path("study/<int:pk>/", views.session_view, name="session"),
    path("study/<int:pk>/answer/", views.answer, name="answer"),
    path("study/<int:pk>/end/", views.end, name="end"),
]
