"""Security headers not covered by Django's built-in defaults.

Django's SecurityMiddleware / XFrameOptionsMiddleware already send
X-Frame-Options, X-Content-Type-Options and Referrer-Policy out of the box;
see settings.py for the HSTS / secure-cookie settings (production only).
Content-Security-Policy has no Django built-in, hence this middleware.
"""


class ContentSecurityPolicyMiddleware:
    """Sets a Content-Security-Policy header scoped to the origins this
    project actually loads from: same-origin, jsDelivr (Bootstrap) and
    Google Fonts. Inline event handlers/scripts are not allowed; the one
    piece of inline JS the templates used to have (timezone auto-detect) was
    moved to static/js/tz-detect.js specifically so script-src doesn't need
    'unsafe-inline'. Inline `style="..."` attributes are still used across
    the templates, so style-src keeps 'unsafe-inline' for now.
    """

    POLICY = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Skip /admin/: Django admin and django-celery-beat's admin widgets
        # rely on inline scripts this project doesn't control, and the admin
        # is staff-only rather than the public-facing surface this policy is
        # meant to harden.
        if not request.path.startswith("/admin/"):
            response.setdefault("Content-Security-Policy", self.POLICY)
        return response
