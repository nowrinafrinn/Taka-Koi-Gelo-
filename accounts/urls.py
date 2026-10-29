from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='accounts/login.html',
            redirect_authenticated_user=True,
        ),
        name='login',
    ),
    # Django's LogoutView only accepts POST, so a link or <img> on another
    # site cannot silently log the user out.
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
