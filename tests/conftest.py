import itertools

import pytest

from accounts.models import User
from courses.models import Course

PASSWORD = "correct-horse-battery-staple"

_counter = itertools.count()


@pytest.fixture
def make_user(db):
    def make(username=None, **kwargs):
        n = next(_counter)
        username = username or f"user{n}"
        kwargs.setdefault("email", f"{username}@example.com")
        return User.objects.create_user(username=username, password=PASSWORD, **kwargs)

    return make


@pytest.fixture
def user(make_user):
    return make_user("alice")


@pytest.fixture
def other_user(make_user):
    return make_user("bob")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def make_course(db):
    def make(owner, name="Biology 101", **kwargs):
        return Course.objects.create(owner=owner, name=name, **kwargs)

    return make


HTMX = {"HTTP_HX_REQUEST": "true"}
