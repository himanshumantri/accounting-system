"""Reports as plain data (replaces ReportPreps.py and the Canvas drawing in FormDialogs.ReportFormats).

Balances are summed from the ledger and cross-checked against chart.balance. Only posted entries
reach the ledger, so draft accruals never appear here.
"""
from decimal import Decimal

from sqlalchemy import func, select

from ..models import chart, journal, ledger
from .posting import NotFound, money

ZERO = Decimal("0.00")


def category(account: int) -> str:
    if 100 <= account < 200:
        return "asset"
    if 200 <= account < 300:
        return "liability"
    if 300 <= account < 400:
        return "equity"
    if 400 <= account < 500:
        return "revenue"
    if 500 <= account < 700:
        return "expense"
    return "other"


def account_balances(conn) -> list[dict]:
    stmt = (
        select(chart.c.account, chart.c.name, chart.c.type, chart.c.balance,
               func.coalesce(func.sum(ledger.c.amount), 0).label("total"))
        .select_from(chart.outerjoin(ledger, ledger.c.account == chart.c.account))
        .group_by(chart.c.account, chart.c.name, chart.c.type, chart.c.balance)
        .order_by(chart.c.account)
    )
    return [{"account": r.account, "name": r.name, "type": r.type,
             "chart_balance": money(r.balance), "balance": money(r.total)} for r in conn.execute(stmt)]


# The side on which each statement section normally increases.
NORMAL_SIDE = {"asset": "DEBIT", "expense": "DEBIT", "liability": "CREDIT", "equity": "CREDIT", "revenue": "CREDIT"}


def _total(rows) -> Decimal:
    return sum((r["balance"] for r in rows), ZERO)


def _section(rows, cat: str) -> list[dict]:
    """Rows of one statement section. An account on the opposite side to the section's normal side
    (accumulated depreciation among assets, drawings among equity, sales returns among revenue) is a
    contra account: its balance counts negatively, so section totals subtract it."""
    normal = NORMAL_SIDE[cat]
    out = []
    for r in rows:
        if category(r["account"]) == cat:
            contra = r["type"] != normal
            out.append({**r, "balance": -r["balance"] if contra else r["balance"], "contra": contra})
    return out


def list_chart(conn) -> list[dict]:
    return [{"account": r["account"], "name": r["name"], "type": r["type"], "balance": r["chart_balance"]}
            for r in account_balances(conn)]


def ledger_account(conn, account: int) -> dict:
    acct = conn.execute(select(chart).where(chart.c.account == account)).first()
    if acct is None:
        raise NotFound(f"Account {account} not found.")
    rows = conn.execute(
        select(ledger.c.transact, journal.c.entry_date, journal.c.description, ledger.c.amount, ledger.c.balance)
        .select_from(ledger.join(journal, journal.c.transact == ledger.c.transact))
        .where(ledger.c.account == account).order_by(ledger.c.id))
    return {"account": acct.account, "name": acct.name, "type": acct.type,
            "entries": [{"transact": r.transact, "date": r.entry_date, "description": r.description,
                         "amount": money(r.amount), "balance": money(r.balance)} for r in rows]}


def trial_balance(conn) -> dict:
    """Natural balances grouped by the account's normal side. Debits must equal credits."""
    rows = account_balances(conn)
    debits = [r for r in rows if r["type"] == "DEBIT"]
    credits = [r for r in rows if r["type"] == "CREDIT"]
    total_debits, total_credits = _total(debits), _total(credits)
    return {
        "debits": debits, "credits": credits,
        "total_debits": total_debits, "total_credits": total_credits,
        "balanced": total_debits == total_credits,
        # Chart balances that no longer agree with the ledger (should always be empty)
        "mismatches": [r["account"] for r in rows if r["balance"] != r["chart_balance"]],
    }


def income_statement(conn) -> dict:
    rows = account_balances(conn)
    revenue, expenses = _section(rows, "revenue"), _section(rows, "expense")
    total_revenue, total_expenses = _total(revenue), _total(expenses)
    return {"revenue": revenue, "expenses": expenses, "total_revenue": total_revenue,
            "total_expenses": total_expenses, "net_income": total_revenue - total_expenses}


def balance_sheet(conn) -> dict:
    """Assets = liabilities + equity. Retained earnings (399) is shown once: its own balance plus
    current-period net income (revenue - expenses)."""
    rows = account_balances(conn)
    income = income_statement(conn)
    assets, liabilities = _section(rows, "asset"), _section(rows, "liability")
    equity_all = _section(rows, "equity")
    equity = [r for r in equity_all if r["account"] != 399]
    booked = next((r["balance"] for r in equity_all if r["account"] == 399), ZERO)
    retained = {"account": 399, "name": "RETAINED EARNINGS", "type": "CREDIT", "contra": False,
                "balance": booked + income["net_income"]}
    total_assets, total_liabilities = _total(assets), _total(liabilities)
    total_equity = _total(equity) + retained["balance"]
    return {
        "assets": assets, "liabilities": liabilities, "equity": equity + [retained],
        "total_assets": total_assets, "total_liabilities": total_liabilities, "total_equity": total_equity,
        "balanced": total_assets == total_liabilities + total_equity,
    }
