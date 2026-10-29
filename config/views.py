import hmac

from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from django.views.decorators.http import require_GET


@require_GET
def healthz(request):
    """Tiny endpoint the host pings to know the app process is alive.

    Deliberately does not touch the database, so it stays fast and cannot
    fail because of a slow free-tier database.
    """
    return HttpResponse('ok', content_type='text/plain')


@require_GET
def healthz_db(request):
    """Checks the database is reachable. Called once a day by Vercel Cron,
    which also counts as activity so the free Supabase project is less likely
    to be paused for inactivity.

    When CRON_SECRET is set, Vercel sends it as a Bearer token; anyone else
    gets 401, so strangers cannot use this endpoint to load the database.
    """
    if settings.CRON_SECRET:
        expected = f'Bearer {settings.CRON_SECRET}'
        given = request.headers.get('Authorization', '')
        if not hmac.compare_digest(given, expected):  # constant-time comparison
            return HttpResponse('unauthorized', status=401, content_type='text/plain')
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return HttpResponse('database unavailable', status=503, content_type='text/plain')
    return HttpResponse('ok', content_type='text/plain')
