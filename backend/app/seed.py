"""Optional demo data: the desktop app's sample chart and journal (OpenAccounting.db), re-entered with
positive amounts and correct debit/credit sides so the books balance. Run: python -m app.seed

Final balances match the old sample: revenue 223.00, expenses 219.81, retained earnings 3.19.
"""
from datetime import date

from sqlalchemy import select

from . import db
from .models import chart
from .services import posting

DEMO_ACCOUNTS = [
    (110, "BANK", "DEBIT"),
    (401, "Customer 1", "CREDIT"),
    (402, "Customer 2", "CREDIT"),
    (420, "General Sales", "CREDIT"),
    (501, "Jones Supply Co", "DEBIT"),
    (502, "Wilson Industrial Tech", "DEBIT"),
    (503, "Supplier 3", "DEBIT"),
    (510, "Rent", "DEBIT"),
    (520, "Electric Company", "DEBIT"),
    (521, "City Water and Sewer", "DEBIT"),
    (600, "ADJUSTMENTS", "DEBIT"),
]

# (date, description, debit, credit, amount)
DEMO_ENTRIES = [
    (date(2018, 10, 20), "Start-up Cash", 110, 300, "1000.00"),
    (date(2018, 10, 22), "Bill 1", 500, 220, "10.23"),
    (date(2018, 10, 20), "Pay bill", 220, 110, "10.23"),
    (date(2018, 10, 22), "Income", 120, 400, "100.00"),
    (date(2018, 10, 24), "Expense Posting", 500, 220, "29.12"),
    (date(2018, 10, 24), "Pay bill 2", 220, 110, "29.12"),
    (date(2018, 10, 30), "A sundry expense", 500, 220, "55.34"),
    (date(2018, 10, 31), "Pay the last bill", 220, 110, "55.34"),
    (date(2018, 11, 18), "Sale Mrs Jones invoice $123", 120, 420, "123.00"),
    (date(2018, 11, 18), "Payment on account invoice #123 Jones", 110, 120, "123.00"),
    (date(2018, 3, 30), "Electricity for March 2018 due Mar 30", 500, 220, "125.12"),
    (date(2018, 3, 30), "Pay electricity for March", 220, 110, "125.12"),
    (date(2018, 11, 18), "Move all electric expenses to sub-account 520", 520, 500, "125.12"),
]


def seed() -> None:
    db.init_db()
    with db.engine.begin() as conn:
        if conn.execute(select(chart.c.account).where(chart.c.account == 110)).first():
            print("Demo data already present; nothing to do.")
            return
        for account, name, acct_type in DEMO_ACCOUNTS:
            posting.add_account(conn, account=account, name=name, acct_type=acct_type)
        for entry_date, description, debit, credit, amount in DEMO_ENTRIES:
            posting.record_entry(conn, entry_date=entry_date, description=description,
                                 debit_account=debit, credit_account=credit, amount=amount)
    print("Demo data loaded.")


if __name__ == "__main__":
    seed()
