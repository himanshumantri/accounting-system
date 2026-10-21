import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    """A fresh SQLite database per test, with system accounts, wired in as db.engine."""
    eng = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(db, "engine", eng)
    db.init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def conn(engine):
    with engine.begin() as connection:
        yield connection
