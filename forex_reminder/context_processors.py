from django.conf import settings


def site(request):
    """Site identity for SEO meta tags (canonical URL, Open Graph, Twitter
    card) — see base.html. Uses the configured SITE_SCHEME/SITE_DOMAIN
    rather than request.get_host() so the URLs stay stable even when
    ALLOWED_HOSTS lists more than one alias (e.g. a cPanel test hostname).
    """
    return {
        "site_name": settings.SITE_NAME,
        "site_url": f"{settings.SITE_SCHEME}://{settings.SITE_DOMAIN}",
    }
