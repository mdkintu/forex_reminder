"""URL configuration for forex_reminder project."""

from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from forex_reminder.health import health
from trades.api import mt5_sync

urlpatterns = [
    # Loaded by the uptime monitor (see forex_reminder/health.py).
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    # django-allauth handles auth (login, signup, logout, password reset, etc.)
    path("accounts/", include("allauth.urls")),
    # Local accounts app. The root URL ("") serves the public landing page
    # via accounts.views.home, plus /dashboard/ and /profile/ for
    # authenticated users.
    path("", include("accounts.urls")),
    path("trades/", include("trades.urls")),
    # Called by the FAIR Sync MT5 Expert Advisor (mt5/FAIR_Sync.mq5).
    path("api/mt5/sync/", mt5_sync, name="mt5_sync"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
