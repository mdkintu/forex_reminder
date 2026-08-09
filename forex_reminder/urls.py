"""URL configuration for forex_reminder project."""

from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    # django-allauth handles auth (login, signup, logout, password reset, etc.)
    path("accounts/", include("allauth.urls")),
    # Local accounts app. The root URL ("") serves the public landing page
    # via a TemplateView (see accounts.views.HomeView), plus /dashboard/ and
    # /profile/ for authenticated users.
    path("", include("accounts.urls")),
    path("trades/", include("trades.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
