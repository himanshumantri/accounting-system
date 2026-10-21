import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.models import metadata  # noqa: E402


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    """A fresh database per test, with system accounts, wired in as db.engine.

    SQLite by default. Set TEST_DATABASE_URL to a Postgres URL to run the same tests against
    Postgres (all tables in that database are dropped first, so use a throwaway database).
    """
    url = os.environ.get("TEST_DATABASE_URL")
    eng = db.make_engine(url or f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(db, "engine", eng)
    if url:
        metadata.drop_all(eng)
    db.init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def conn(engine):
    with engine.begin() as connection:
        yield connection
