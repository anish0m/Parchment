"""Settings shared by every environment. Values come from environment variables."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_q",
    "accounts",
    "courses",
    "materials",
    "flashcards",
    "study",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "parchment.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "parchment.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# Static files (CSS, JS) are collected into STATIC_ROOT and served by WhiteNoise.
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = env.path("DJANGO_STATIC_ROOT", default=BASE_DIR / "staticfiles")

# Media files are user uploads (PDF notes).
MEDIA_URL = "media/"
MEDIA_ROOT = env.path("DJANGO_MEDIA_ROOT", default=BASE_DIR / "media")
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# Limits for uploaded study materials.
MATERIAL_MAX_UPLOAD_MB = env.int("MATERIAL_MAX_UPLOAD_MB", default=20)
MATERIAL_MAX_PDF_PAGES = env.int("MATERIAL_MAX_PDF_PAGES", default=300)
MATERIAL_MAX_TEXT_CHARS = env.int("MATERIAL_MAX_TEXT_CHARS", default=300_000)

# Background tasks (Django-Q2), using PostgreSQL as the queue. Run workers with
# `python manage.py qcluster`. With Q_SYNC=True tasks run inline, without a worker.
Q_CLUSTER = {
    "name": "parchment",
    "orm": "default",
    "workers": env.int("Q_WORKERS", default=2),
    "timeout": env.int("Q_TIMEOUT", default=900),  # seconds a task may run
    "retry": env.int("Q_TIMEOUT", default=900) + 300,  # must exceed timeout
    "max_attempts": 1,  # failures are shown to the user, who can retry
    "catch_up": False,
    "sync": env.bool("Q_SYNC", default=False),
    "label": "Background tasks",
}

# Flashcard generation.
# CARD_GENERATOR: "auto" uses Claude when an Anthropic API key is set, else the
# built-in rules; "claude" or "rules" force one. Claude failures fall back to rules.
CARD_GENERATOR = env("CARD_GENERATOR", default="auto")
CARD_GENERATION_MODEL = env("CARD_GENERATION_MODEL", default="claude-opus-5")
CARD_GENERATION_EFFORT = env("CARD_GENERATION_EFFORT", default="medium")
# EMBEDDING_BACKEND: "auto" uses sentence-transformers when installed and the model
# loads, else TF-IDF; "sentence-transformers" or "tfidf" force one.
EMBEDDING_BACKEND = env("EMBEDDING_BACKEND", default="auto")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="sentence-transformers/all-MiniLM-L6-v2")
MAX_CONCEPTS_PER_MATERIAL = env.int("MAX_CONCEPTS_PER_MATERIAL", default=12)
MAX_CARDS_PER_CONCEPT = env.int("MAX_CARDS_PER_CONCEPT", default=5)
MAX_CARDS_PER_MATERIAL = env.int("MAX_CARDS_PER_MATERIAL", default=60)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "courses:list"
LOGOUT_REDIRECT_URL = "home"

DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default="Parchment <noreply@localhost>")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default="INFO")},
}
