from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("profile/test-reminder/", views.test_reminder, name="test_reminder"),
    path("calendar/<str:token>.ics", views.calendar_feed, name="calendar_feed"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("contact/", views.contact, name="contact"),
    path("telegram/webhook/", views.telegram_webhook, name="telegram_webhook"),
]
