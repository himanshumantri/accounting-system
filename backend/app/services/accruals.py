"""Accrual entries generated from a flagged transaction.

Every generated entry is saved as a draft (journal.posted = False) that does not touch the ledger or
chart balances until the user approves it (posting.post_draft).

  accrued_expense   Dr <expense> / Cr Accrued Expenses (230), dated period end
  accrued_revenue   Dr Accrued Revenue (135) / Cr <revenue>,  dated period end
  prepaid_expense   draft of the entry as typed (Dr prepaid asset / Cr cash), plus monthly drafts
                    Dr <recognition expense> / Cr prepaid asset
  deferred_revenue  draft of the entry as typed (Dr cash / Cr deferred revenue), plus monthly drafts
                    Dr deferred revenue / Cr <recognition revenue>
  auto_reverse (accrued types only) adds a draft on the first day of the next period with the
  debit and credit swapped, so the real invoice or payment does not double count.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, insert, select, update

from ..models import accruals, journal
from .posting import CENT, AccountingError, NotFound, check_amount, check_description, get_accounts, record_entry
from .reports import category

ACCRUED_EXPENSES, ACCRUED_REVENUE = 230, 135
TYPES = ("accrued_expense", "accrued_revenue", "prepaid_expense", "deferred_revenue")
MAX_MONTHS = 120


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(d: date, n: int) -> tuple[int, int]:
    index = d.year * 12 + (d.month - 1) + n
    return index // 12, index % 12 + 1


def split_evenly(amount: Decimal, months: int) -> list[Decimal]:
    """Equal monthly amounts to the cent; the last month absorbs any rounding remainder."""
    base = (amount / months).quantize(CENT)
    parts = [base] * (months - 1)
    parts.append(amount - sum(parts, Decimal("0.00")))
    return parts


def _require_category(conn, account: int, expected: str, label: str) -> None:
    get_accounts(conn, [account])
    if category(account) != expected:
        raise AccountingError(f"{label} account {account} must be a(n) {expected} account.")


def create_accrual(conn, *, type: str, description: str, amount, entry_date: date,
                   debit_account: int | None = None, credit_account: int | None = None,
                   recognition_account: int | None = None, period_end: date | None = None,
                   months: int | None = None, auto_reverse: bool = False) -> dict:
    if type not in TYPES:
        raise AccountingError("Accrual type must be one of: " + ", ".join(TYPES))
    amount = check_amount(amount)
    description = check_description(description)
    source_transact = None
    drafts: list[dict] = []  # (date, debit, credit, amount, description)

    if type in ("accrued_expense", "accrued_revenue"):
        if period_end is None:
            raise AccountingError("period_end is required for accrued entries.")
        if type == "accrued_expense":
            if debit_account is None:
                raise AccountingError("debit_account (the expense account) is required.")
            _require_category(conn, debit_account, "expense", "Expense")
            credit_account = credit_account or ACCRUED_EXPENSES
            _require_category(conn, credit_account, "liability", "Accrued liability")
        else:
            if credit_account is None:
                raise AccountingError("credit_account (the revenue account) is required.")
            _require_category(conn, credit_account, "revenue", "Revenue")
            debit_account = debit_account or ACCRUED_REVENUE
            _require_category(conn, debit_account, "asset", "Accrued receivable")
        drafts.append((period_end, debit_account, credit_account, amount, f"Accrual: {description}"))
        if auto_reverse:
            drafts.append((period_end + timedelta(days=1), credit_account, debit_account, amount,
                           f"Reversal of accrual: {description}"))
    else:
        if auto_reverse:
            raise AccountingError("auto_reverse applies to accrued_expense and accrued_revenue only.")
        if not months or not 1 <= months <= MAX_MONTHS:
            raise AccountingError(f"months must be between 1 and {MAX_MONTHS}.")
        if debit_account is None or credit_account is None or recognition_account is None:
            raise AccountingError("debit_account, credit_account and recognition_account are required.")
        if type == "prepaid_expense":
            _require_category(conn, debit_account, "asset", "Prepaid")
            _require_category(conn, recognition_account, "expense", "Recognition")
            drafts_debit, drafts_credit = recognition_account, debit_account
        else:
            _require_category(conn, credit_account, "liability", "Deferred revenue")
            _require_category(conn, recognition_account, "revenue", "Recognition")
            drafts_debit, drafts_credit = credit_account, recognition_account
        for i, part in enumerate(split_evenly(amount, months)):
            year, month = _add_months(entry_date, i)
            drafts.append((month_end(year, month), drafts_debit, drafts_credit, part,
                           f"{description} ({i + 1}/{months})"))

    accrual_id = conn.execute(insert(accruals).values(
        type=type, description=description, amount=amount,
        debit_account=debit_account, credit_account=credit_account,
        recognition_account=recognition_account, period_end=period_end, months=months,
        auto_reverse=auto_reverse, status="open")).inserted_primary_key[0]

    if type in ("prepaid_expense", "deferred_revenue"):
        source_transact = record_entry(conn, entry_date=entry_date, description=description,
                                       debit_account=debit_account, credit_account=credit_account,
                                       amount=amount, posted=False, accrual_id=accrual_id)
        conn.execute(update(accruals).where(accruals.c.id == accrual_id).values(source_transact=source_transact))

    draft_ids = [source_transact] if source_transact else []
    for d, dr, cr, amt, text in drafts:
        draft_ids.append(record_entry(conn, entry_date=d, description=text, debit_account=dr,
                                      credit_account=cr, amount=amt, posted=False, accrual_id=accrual_id))
    return {"accrual_id": accrual_id, "source_transact": source_transact, "draft_transacts": draft_ids}


def list_drafts(conn) -> list[dict]:
    rows = conn.execute(
        select(journal, accruals.c.type.label("accrual_type"))
        .select_from(journal.join(accruals, accruals.c.id == journal.c.accrual_id))
        .where(journal.c.posted.is_(False)).order_by(journal.c.entry_date, journal.c.transact))
    return [{"transact": r.transact, "date": r.entry_date, "description": r.description,
             "debit_account": r.debit_account, "credit_account": r.credit_account,
             "amount": r.amount, "accrual_id": r.accrual_id, "accrual_type": r.accrual_type} for r in rows]


def discard_accrual(conn, accrual_id: int) -> int:
    """Delete every remaining draft of an accrual. Posted entries are never touched."""
    if conn.execute(select(accruals.c.id).where(accruals.c.id == accrual_id)).first() is None:
        raise NotFound(f"Accrual {accrual_id} not found.")
    result = conn.execute(delete(journal).where(journal.c.accrual_id == accrual_id, journal.c.posted.is_(False)))
    conn.execute(update(accruals).where(accruals.c.id == accrual_id).values(status="complete"))
    return result.rowcount
