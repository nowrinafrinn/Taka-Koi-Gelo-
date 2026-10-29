from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect
from django.views.generic import CreateView

from .forms import SignUpForm


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = 'accounts/signup.html'

    def dispatch(self, request, *args, **kwargs):
        # Someone already logged in has no reason to see the sign-up page.
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)  # log straight in after signing up
        messages.success(self.request, f'Welcome, {user.username}! Let’s find out where your taka goes.')
        return redirect(settings.LOGIN_REDIRECT_URL)
