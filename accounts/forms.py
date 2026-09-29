from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["placeholder"] = "Your username"
        self.fields["password"].widget.attrs["placeholder"] = "••••••••"


class SignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["placeholder"] = "Choose a username"
        self.fields["email"].widget.attrs["placeholder"] = "you@example.com"
        self.fields["username"].help_text = "Letters, digits and @ . + - _ only."
        self.fields[
            "password1"
        ].help_text = "At least 8 characters, not too common and not only numbers."
        self.fields["password2"].help_text = ""
        # Alpine (in the template) compares the two passwords as they're typed.
        self.fields["password1"].widget.attrs["x-model"] = "password1"
        self.fields["password2"].widget.attrs["x-model"] = "password2"

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class UsernameForm(forms.ModelForm):
    """Settings: change the username chosen at sign-up."""

    class Meta:
        model = User
        fields = ("username",)
        help_texts = {"username": "Letters, digits and @ . + - _ only."}

    def clean_username(self):
        username = self.cleaned_data["username"]
        taken = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username


class DeleteAccountForm(forms.Form):
    """Settings: deleting the account needs the current password."""

    password = forms.CharField(
        label="Your password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("That password is incorrect.")
        return password
