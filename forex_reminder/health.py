"""/health/: the page the uptime monitor loads every few minutes.

"ok" (200) means the app is up, the database answers and every migration is
applied. A pending migration gives 503: on 2026-11-23 new code ran before
`migrate`, and only the pages that touch the new columns broke while the
home page stayed up. If the database is unreachable, the query raises and
the monitor gets a 500.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse
from django.views.decorators.cache import never_cache


@never_cache
def health(request):
    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if pending:
        return HttpResponse(
            f"{len(pending)} unapplied migration(s)", status=503, content_type="text/plain"
        )
    return HttpResponse("ok", content_type="text/plain")
