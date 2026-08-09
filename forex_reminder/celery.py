import os

from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "forex_reminder.settings")

app = Celery(
    "forex_reminder",
    # Explicitly list task modules so they are always registered, even if
    # autodiscovery via the Django fixup isn't available (e.g. in some
    # management-command or test contexts).
    include=["trades.tasks"],
)

# Use a string here so the worker doesn't have to serialize the configuration
# object to the child processes. The namespace=CELERY means all celery-related
# settings in settings.py should be prefixed with 'CELERY_'.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
