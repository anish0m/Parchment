from django.urls import path

from . import views

app_name = "flashcards"

urlpatterns = [
    path("courses/<int:course_pk>/cards/", views.FlashcardListView.as_view(), name="list"),
    path("courses/<int:course_pk>/cards/new/", views.FlashcardCreateView.as_view(), name="create"),
    path("cards/<int:pk>/", views.FlashcardDetailView.as_view(), name="detail"),
    path("cards/<int:pk>/edit/", views.FlashcardUpdateView.as_view(), name="update"),
    path("cards/<int:pk>/delete/", views.FlashcardDeleteView.as_view(), name="delete"),
]
