"""Settings that matter when running on Cloud Run + Neon."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import clock, db
from app.main import app
from app.services import recurring


@pytest.mark.parametrize("raw,expected", [
    ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql://u:p@h/db?sslmode=require\n", "postgresql+psycopg://u:p@h/db?sslmode=require"),
    ("  postgresql+psycopg://u:p@h/db  ", "postgresql+psycopg://u:p@h/db"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_database_url_is_normalised(raw, expected):
    assert db.normalize_url(raw) == expected


def test_postgres_engine_is_tuned_for_neon_and_cloud_run():
    eng = db.make_engine("postgresql://u:p@localhost/db")  # lazy: nothing connects
    assert eng.dialect.name == "postgresql" and eng.dialect.driver == "psycopg"
    assert eng.pool.size() == 5 and eng.pool._max_overflow == 5 and eng.pool._pre_ping is True
    assert eng.pool._recycle == 300
    eng.dispose()


def test_clock_uses_app_timezone(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Pacific/Kiritimati")  # UTC+14
    assert clock.today() == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    monkeypatch.delenv("APP_TIMEZONE")
    assert clock.today() == datetime.now(ZoneInfo("UTC")).date()


def test_invalid_timezone_fails_at_startup(engine, monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Mars/Olympus")
    with pytest.raises(Exception):
        with TestClient(app):
            pass


def test_recurring_uses_the_app_clock(engine, monkeypatch):
    with engine.begin() as c:
        recurring.create(c, description="Rent", debit_account=500, credit_account=220, amount="10",
                         frequency="monthly", first_run=date(2024, 5, 31))
    monkeypatch.setattr(clock, "today", lambda: date(2024, 5, 30))
    assert recurring.run_due()["posted"] == []          # not yet due in the app's timezone
    monkeypatch.setattr(clock, "today", lambda: date(2024, 5, 31))
    assert len(recurring.run_due()["posted"]) == 1


def test_secrets_with_stray_whitespace_still_work(engine, monkeypatch):
    monkeypatch.setenv("RECURRING_RUN_TOKEN", "abc123\n")
    with TestClient(app) as client:
        assert client.post("/recurring/run", headers={"X-Run-Token": "abc123"}).status_code == 200
        assert client.post("/recurring/run", headers={"X-Run-Token": "nope"}).status_code == 403


def test_cors_origin_with_trailing_slash(monkeypatch):
    # The configured origin is normalised, so a pasted "https://x.web.app/" still matches the browser's Origin.
    import importlib
    import app.main as main
    monkeypatch.setenv("CORS_ORIGINS", "https://demo.web.app/, https://demo.firebaseapp.com")
    reloaded = importlib.reload(main)
    try:
        with TestClient(reloaded.app) as client:
            r = client.options("/chart", headers={"Origin": "https://demo.web.app",
                                                  "Access-Control-Request-Method": "GET"})
            assert r.headers.get("access-control-allow-origin") == "https://demo.web.app"
            r = client.options("/chart", headers={"Origin": "https://evil.example",
                                                  "Access-Control-Request-Method": "GET"})
            assert "access-control-allow-origin" not in r.headers
    finally:
        monkeypatch.undo()
        importlib.reload(main)
