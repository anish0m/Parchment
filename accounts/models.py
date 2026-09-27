from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Project user model.

    Defined from the start so fields can be added later without a painful
    swap of AUTH_USER_MODEL. Email is required and unique so password reset
    always reaches exactly one account.
    """

    email = models.EmailField("email address", unique=True)
