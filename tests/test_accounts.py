import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from .conftest import PASSWORD

User = get_user_model()


def test_custom_user_model_is_active():
    assert User._meta.label == "accounts.User"


@pytest.mark.django_db
def test_signup_creates_user_and_logs_in(client):
    response = client.post(
        reverse("signup"),
        {
            "username": "carol",
            "email": "Carol@Example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    # New accounts land on their profile (logging in goes to the course list).
    assert response.status_code == 302
    assert response.url == reverse("profile")
    user = User.objects.get(username="carol")
    assert user.email == "carol@example.com"
    assert client.get(reverse("courses:list")).status_code == 200


def test_signup_rejects_duplicate_email_case_insensitively(client, user):
    response = client.post(
        reverse("signup"),
        {
            "username": "someone-else",
            "email": user.email.upper(),
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 200
    assert "already exists" in response.content.decode()
    assert not User.objects.filter(username="someone-else").exists()


def test_signup_page_redirects_signed_in_user(auth_client):
    response = auth_client.get(reverse("signup"))

    assert response.status_code == 302
    assert response.url == reverse("courses:list")


def test_login_and_logout(client, user):
    response = client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
    assert response.status_code == 302
    assert response.url == reverse("courses:list")

    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert client.get(reverse("courses:list")).status_code == 302


def test_login_rejects_wrong_password(client, user):
    response = client.post(reverse("login"), {"username": "alice", "password": "wrong"})

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_password_reset_flow(client, user):
    response = client.post(reverse("password_reset"), {"email": user.email})
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Reset your Parchment password"

    link = re.search(r"https?://[^/]+(/\S+)", mail.outbox[0].body).group(1)
    # The first visit swaps the token in the URL for one kept in the session.
    response = client.get(link, follow=True)
    set_password_url = response.redirect_chain[-1][0]

    new_password = "a-brand-new-passphrase"
    response = client.post(
        set_password_url, {"new_password1": new_password, "new_password2": new_password}
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password(new_password)


def test_password_change_requires_login(client):
    response = client.get(reverse("password_change"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_home_redirects_signed_in_user_to_courses(auth_client):
    response = auth_client.get(reverse("home"))

    assert response.status_code == 302
    assert response.url == reverse("courses:list")


@pytest.mark.django_db
def test_home_shows_signup_links_when_signed_out(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert reverse("signup") in response.content.decode()
