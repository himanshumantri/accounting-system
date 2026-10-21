"""Recurring journal entries. run_due() is idempotent: each occurrence posts and advances next_run in
one transaction, so a rerun (or a crash halfway) never double-posts, and missed periods are caught up."""
import calendar
from datetime import date, timedelta

from sqlalchemy import insert, select, update

from .. import db
from ..models import recurring_entries as rec
from .posting import (AccountingError, NotFound, check_amount, check_description, get_accounts, record_entry)

FREQUENCIES = ("weekly", "monthly")
MAX_PER_RUN = 400  # per entry; a very old start date is worked off over several runs, not one huge request


def _clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def advance(current: date, frequency: str, day: int | None) -> date:
    if frequency == "weekly":
        return current + timedelta(days=7)
    year, month = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
    return _clamp_day(year, month, day or current.day)


def create(conn, *, description: str, debit_account: int, credit_account: int, amount, frequency: str,
           first_run: date, end_date: date | None = None) -> int:
    description = check_description(description)
    amount = check_amount(amount)
    if frequency not in FREQUENCIES:
        raise AccountingError("frequency must be 'weekly' or 'monthly'.")
    if debit_account == credit_account:
        raise AccountingError("Debit and credit accounts must be different.")
    if end_date and end_date < first_run:
        raise AccountingError("end_date cannot be before the first run date.")
    get_accounts(conn, [debit_account, credit_account])
    return conn.execute(insert(rec).values(
        description=description, debit_account=debit_account, credit_account=credit_account, amount=amount,
        frequency=frequency, day=first_run.day if frequency == "monthly" else None,
        next_run=first_run, end_date=end_date, active=True)).inserted_primary_key[0]


def set_active(conn, rec_id: int, active: bool, today: date | None = None) -> None:
    """Pause or resume. Resuming skips the periods that fell while paused (they are not back-posted)."""
    row = conn.execute(select(rec).where(rec.c.id == rec_id).with_for_update()).first()
    if row is None:
        raise NotFound(f"Recurring entry {rec_id} not found.")
    values = {"active": active}
    if active and not row.active:
        today = today or date.today()
        next_run = row.next_run
        while next_run < today and not (row.end_date and next_run > row.end_date):
            next_run = advance(next_run, row.frequency, row.day)
        values["next_run"] = next_run
    conn.execute(update(rec).where(rec.c.id == rec_id).values(**values))


def list_all(conn) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(select(rec).order_by(rec.c.id))]


def run_due(today: date | None = None) -> dict:
    """Post every occurrence that is due on or before `today`. Opens its own transactions."""
    today = today or date.today()
    with db.engine.connect() as conn:
        ids = [r.id for r in conn.execute(select(rec.c.id).where(rec.c.active.is_(True), rec.c.next_run <= today))]
    posted, errors, truncated = [], [], False
    for rec_id in ids:
        count = 0
        while True:
            if count >= MAX_PER_RUN:
                truncated = True
                break
            try:
                with db.engine.begin() as conn:  # one occurrence per transaction
                    row = conn.execute(select(rec).where(rec.c.id == rec_id).with_for_update()).first()
                    if row is None or not row.active or row.next_run > today:
                        break
                    if row.end_date and row.next_run > row.end_date:
                        conn.execute(update(rec).where(rec.c.id == rec_id).values(active=False))
                        break
                    transact = record_entry(conn, entry_date=row.next_run, description=row.description,
                                            debit_account=row.debit_account, credit_account=row.credit_account,
                                            amount=row.amount, posted=True)
                    conn.execute(update(rec).where(rec.c.id == rec_id)
                                 .values(next_run=advance(row.next_run, row.frequency, row.day)))
                    posted.append({"recurring_id": rec_id, "transact": transact, "date": row.next_run})
                    count += 1
            except AccountingError as exc:
                errors.append({"recurring_id": rec_id, "error": str(exc)})
                break
    return {"posted": posted, "errors": errors, "truncated": truncated}
