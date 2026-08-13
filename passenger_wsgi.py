"""Passenger WSGI entry point for cPanel shared hosting.

cPanel's "Setup Python App" (Passenger) serves this project by importing the
``application`` callable from this file (matching the "Application entry
point" = ``application`` in the cPanel form).

Copy this project so that this file sits at the configured "Application root"
(next to manage.py and requirements.txt). cPanel/Passenger reads settings from
the virtual environment + any env vars you set in the cPanel app form.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "forex_reminder.settings")

# In case Passenger doesn't expose the venv on PATH automatically.
# (Optional: uncomment and set to your cPanel virtualenv path if needed.)
# VENV = "/home/USER/virtualenvs/PYTHON_VERSION/VENV_NAME"
# if os.path.isdir(VENV):
#     os.environ["PATH"] = os.path.join(VENV, "bin") + os.pathsep + os.environ["PATH"]

application = get_wsgi_application()

# Serve collected static files (/static/...) directly from Django so the
# admin and site CSS/JS are served even though cPanel's Passenger app has no
# "Static URL/Path" field to map /static/ to the collected staticfiles/ dir.
# In production you'd normally let the web server (Nginx/Apache) serve static
# files instead, but on cPanel/Passenger this is the simplest reliable option.
from django.contrib.staticfiles.handlers import StaticFilesHandler

application = StaticFilesHandler(application)

