from django.contrib.auth.forms import UserCreationForm


class SignUpForm(UserCreationForm):
    """Username + password twice. Django's built-in form already hashes the
    password and runs the AUTH_PASSWORD_VALIDATORS from settings."""

    class Meta(UserCreationForm.Meta):
        fields = ['username']
