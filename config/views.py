from django.http import HttpResponse
from django.views.decorators.http import require_GET


@require_GET
def healthz(request):
    """Tiny endpoint the host pings to know the app process is alive.

    Deliberately does not touch the database, so it stays fast and cannot
    fail because of a slow free-tier database.
    """
    return HttpResponse('ok', content_type='text/plain')
