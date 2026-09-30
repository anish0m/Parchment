"""Settings used by the test suite."""

from .dev import *  # noqa: F403

DEBUG = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Run background tasks inline, and keep tests offline and fast.
Q_CLUSTER = {**Q_CLUSTER, "sync": True}  # noqa: F405
CARD_GENERATOR = "rules"
ANSWER_GRADER = "local"
EMBEDDING_BACKEND = "tfidf"
