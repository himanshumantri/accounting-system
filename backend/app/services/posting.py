"""Journal posting: replaces insertJournalForm.on_click and the AccountDB insert/update methods.

Every function takes an open SQLAlchemy connection and runs inside the caller's transaction, so a
journal entry, its two ledger rows and both chart-balance updates succeed or fail together.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import delete, insert, select, update

from ..models import accruals, chart, journal, ledger

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")
MIN_ACCOUNT, MAX_ACCOUNT = 100, 699  # reports cover 100-699 only


class AccountingError(Exception):
    status = 400


class NotFound(AccountingError):
    status = 404


class Conflict(AccountingError):
    status = 409


def money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(CENT, ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise AccountingError(f"Invalid amount: {value!r}")


def check_amount(value) -> Decimal:
    amount = money(value)
    if amount <= 0:
        raise AccountingError("Amount must be greater than zero (the debit/credit side sets the sign).")
    if amount > MAX_AMOUNT:
        raise AccountingError("Amount is too large.")
    return amount


def check_description(text) -> str:
    text = (text or "").strip()
    if not text:
        raise AccountingError("Description is required.")
    if len(text) > 200:
        raise AccountingError("Description must be 200 characters or fewer.")
    return text


def get_accounts(conn, numbers, lock: bool = False) -> dict:
    """Fetch chart rows by number, failing with NotFound if any is missing."""
    wanted = sorted(set(numbers))
    stmt = select(chart).where(chart.c.account.in_(wanted)).order_by(chart.c.account)
    if lock:
        stmt = stmt.with_for_update()  # consistent order avoids deadlocks; no-op on SQLite
    found = {row.account: row for row in conn.execute(stmt)}
    missing = [a for a in wanted if a not in found]
    if missing:
        raise NotFound("Account(s) not found in chart: " + ", ".join(str(a) for a in missing))
    return found


def _apply(conn, transact: int, debit_account: int, credit_account: int, amount: Decimal) -> None:
    """Post both sides to the ledger and chart. An account moves up when the side matches its
    normal type and down otherwise (the desktop app's getsgnAdjust convention)."""
    accounts = get_accounts(conn, [debit_account, credit_account], lock=True)
    for side, number in (("DEBIT", debit_account), ("CREDIT", credit_account)):
        acct = accounts[number]
        delta = amount if acct.type == side else -amount
        new_balance = money(acct.balance) + delta
        conn.execute(update(chart).where(chart.c.account == number).values(balance=new_balance))
        conn.execute(insert(ledger).values(account=number, transact=transact, amount=delta, balance=new_balance))


def record_entry(conn, *, entry_date: date, description: str, debit_account: int, credit_account: int,
                 amount, posted: bool = True, accrual_id: int | None = None, depends_on: int | None = None) -> int:
    """Validate and store one journal entry. Posted entries hit the ledger; drafts do not."""
    amount = check_amount(amount)
    description = check_description(description)
    if debit_account == credit_account:
        raise AccountingError("Debit and credit accounts must be different.")
    get_accounts(conn, [debit_account, credit_account])
    result = conn.execute(insert(journal).values(
        entry_date=entry_date, description=description, debit_account=debit_account,
        credit_account=credit_account, amount=amount, posted=False, accrual_id=accrual_id,
        depends_on=depends_on))
    transact = result.inserted_primary_key[0]
    if posted:
        _apply(conn, transact, debit_account, credit_account, amount)
        conn.execute(update(journal).where(journal.c.transact == transact).values(posted=True))
    return transact


def _refresh_accrual_status(conn, accrual_id: int | None) -> None:
    if accrual_id is None:
        return
    remaining = conn.execute(select(journal.c.transact).where(
        journal.c.accrual_id == accrual_id, journal.c.posted.is_(False)).limit(1)).first()
    conn.execute(update(accruals).where(accruals.c.id == accrual_id)
                 .values(status="open" if remaining else "complete"))


def _get_draft(conn, transact: int):
    row = conn.execute(select(journal).where(journal.c.transact == transact).with_for_update()).first()
    if row is None:
        raise NotFound(f"Journal entry {transact} not found.")
    if row.posted:
        raise Conflict(f"Journal entry {transact} is already posted.")
    return row


def post_draft(conn, transact: int) -> None:
    """Approve a draft: post it to the ledger exactly once, and only after the entry it depends on."""
    row = _get_draft(conn, transact)
    if row.depends_on is not None:
        parent_posted = conn.execute(select(journal.c.posted).where(journal.c.transact == row.depends_on)).scalar_one()
        if not parent_posted:
            raise Conflict(f"Post entry {row.depends_on} first: entry {transact} depends on it.")
    _apply(conn, transact, row.debit_account, row.credit_account, money(row.amount))
    conn.execute(update(journal).where(journal.c.transact == transact).values(posted=True))
    _refresh_accrual_status(conn, row.accrual_id)


def discard_draft(conn, transact: int) -> None:
    """Delete a draft and any drafts that depend on it (they could never be posted without it)."""
    row = _get_draft(conn, transact)
    conn.execute(delete(journal).where(journal.c.depends_on == transact, journal.c.posted.is_(False)))
    conn.execute(delete(journal).where(journal.c.transact == transact))
    _refresh_accrual_status(conn, row.accrual_id)


def _account_exists(conn, account: int) -> bool:
    return conn.execute(select(chart.c.account).where(chart.c.account == account)).first() is not None


def add_account(conn, *, account: int, name: str, acct_type: str) -> None:
    """New accounts always open at zero: opening balances go through the journal so the books stay
    balanced (the desktop form let you type a starting balance with no matching entry)."""
    name = (name or "").strip()
    acct_type = (acct_type or "").upper()
    if not MIN_ACCOUNT <= account <= MAX_ACCOUNT:
        raise AccountingError(f"Account number must be between {MIN_ACCOUNT} and {MAX_ACCOUNT}.")
    if not name or len(name) > 60:
        raise AccountingError("Name is required (60 characters maximum).")
    if acct_type not in ("DEBIT", "CREDIT"):
        raise AccountingError("Type must be DEBIT or CREDIT.")
    if _account_exists(conn, account):
        raise Conflict(f"Account {account} already exists.")
    conn.execute(insert(chart).values(account=account, name=name, type=acct_type, balance=0))
