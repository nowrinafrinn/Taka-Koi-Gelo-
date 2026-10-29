from django.contrib import admin
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

from . import views


class FaviconRedirect(RedirectView):
    """Some browsers ask for /favicon.ico even when the page names an SVG icon.
    The static URL is resolved per request so hashed production names work."""
    permanent = True

    def get_redirect_url(self, *args, **kwargs):
        return static('img/coin.svg')


urlpatterns = [
    path('favicon.ico', FaviconRedirect.as_view()),
    path('admin/', admin.site.urls),
    path('healthz/', views.healthz, name='healthz'),
    path('healthz/db/', views.healthz_db, name='healthz_db'),
    path('accounts/', include('accounts.urls')),
    path('', include('finance.urls')),
]
