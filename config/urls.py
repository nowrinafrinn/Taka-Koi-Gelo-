from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', views.healthz, name='healthz'),
    path('healthz/db/', views.healthz_db, name='healthz_db'),
    path('accounts/', include('accounts.urls')),
    path('', include('finance.urls')),
]
