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
