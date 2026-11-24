"""Tests for /health/, the page the uptime monitor loads every few minutes."""

import pytest
from django.db.migrations.recorder import MigrationRecorder


@pytest.mark.django_db
def test_health_is_ok_when_database_answers_and_all_migrations_applied(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.content == b"ok"
    # A cached "ok" would hide an outage from the monitor.
    assert "no-store" in response["Cache-Control"]


@pytest.mark.django_db
def test_health_fails_while_a_migration_is_unapplied(client):
    """The 2026-11-23 outage: new code ran before `migrate`. The home page
    (no database use) stayed up, so only this check would have caught it."""
    MigrationRecorder.Migration.objects.filter(app="trades").latest("id").delete()
    response = client.get("/health/")
    assert response.status_code == 503
    assert response.content == b"1 unapplied migration(s)"
