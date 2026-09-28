from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("courses", views.CourseViewSet, basename="course")
router.register("materials", views.MaterialViewSet, basename="material")
router.register("flashcards", views.FlashcardViewSet, basename="flashcard")
router.register("reviews", views.ReviewViewSet, basename="review")

app_name = "api"

urlpatterns = [
    path("v1/", include(router.urls)),
    path("v1/auth/token/", obtain_auth_token, name="token"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerSplitView.as_view(url_name="api:schema"), name="docs"),
]
