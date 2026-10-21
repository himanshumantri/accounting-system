"""Engine setup. DATABASE_URL selects Postgres in production; SQLite is the local/test default."""
import os
import warnings

from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.exc import SAWarning

from .models import SYSTEM_ACCOUNTS, chart, metadata

# SQLite stores NUMERIC as float; we round to cents everywhere, so the warning is noise.
warnings.filterwarnings("ignore", message=".*does \\*not\\* support Decimal.*", category=SAWarning)


def normalize_url(url: str) -> str:
    """Render/Neon hand out postgres:// or postgresql:// URLs; point them at the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str | None = None):
    url = normalize_url(url or os.environ.get("DATABASE_URL") or "sqlite:///./openaccounting.db")
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _enable_fk(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    else:
        eng = create_engine(url, pool_pre_ping=True)
    return eng


# Routes read `db.engine` at call time so tests can swap it.
engine = make_engine()


def init_db(eng=None) -> None:
    """Create tables and make sure the system accounts exist. Safe to run on every start."""
    eng = eng or engine
    metadata.create_all(eng)
    with eng.begin() as conn:
        existing = {r.account for r in conn.execute(select(chart.c.account))}
        for account, name, acct_type in SYSTEM_ACCOUNTS:
            if account not in existing:
                conn.execute(insert(chart).values(account=account, name=name, type=acct_type, balance=0))
