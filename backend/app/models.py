"""Database schema: the single source of truth (replaces OpenAccounting.sql and AccountDB.createAccounts)."""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer,
    MetaData, Numeric, String, Table, Text, func,
)

metadata = MetaData()

Money = Numeric(14, 2)

# Chart of accounts. `type` is the account's normal side; `balance` is its natural balance
# (positive when the account is in its normal state), kept in step with the ledger.
chart = Table(
    "chart", metadata,
    Column("account", Integer, primary_key=True, autoincrement=False),
    Column("name", String(60), nullable=False),
    Column("type", String(6), nullable=False),
    Column("balance", Money, nullable=False, default=0),
    CheckConstraint("type IN ('DEBIT', 'CREDIT')", name="ck_chart_type"),
)

# Accrual definitions (see services/accruals.py). Draft journal rows point back here.
accruals = Table(
    "accruals", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("type", String(20), nullable=False),
    Column("description", String(200), nullable=False),
    Column("amount", Money, nullable=False),
    Column("debit_account", Integer, ForeignKey("chart.account"), nullable=False),
    Column("credit_account", Integer, ForeignKey("chart.account"), nullable=False),
    Column("recognition_account", Integer, ForeignKey("chart.account")),
    Column("period_end", Date),
    Column("months", Integer),
    Column("auto_reverse", Boolean, nullable=False, default=False),
    Column("source_transact", Integer),
    Column("status", String(10), nullable=False, default="open"),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

# One debit + one credit of the same positive amount. `posted` is False for draft
# accrual entries, which never touch the ledger or chart balances until approved.
journal = Table(
    "journal", metadata,
    Column("transact", Integer, primary_key=True, autoincrement=True),
    Column("entry_date", Date, nullable=False),
    Column("description", String(200), nullable=False),
    Column("debit_account", Integer, ForeignKey("chart.account"), nullable=False),
    Column("credit_account", Integer, ForeignKey("chart.account"), nullable=False),
    Column("amount", Money, nullable=False),
    Column("posted", Boolean, nullable=False, default=False),
    Column("accrual_id", Integer, ForeignKey("accruals.id")),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    CheckConstraint("amount > 0", name="ck_journal_amount_positive"),
    CheckConstraint("debit_account <> credit_account", name="ck_journal_distinct_accounts"),
)

# Signed natural-balance movements, as in the desktop app (see posting._apply).
ledger = Table(
    "ledger", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("account", Integer, ForeignKey("chart.account"), nullable=False),
    Column("transact", Integer, ForeignKey("journal.transact"), nullable=False),
    Column("amount", Money, nullable=False),
    Column("balance", Money, nullable=False),
)

accountmemos = Table(
    "accountmemos", metadata,
    Column("memo_id", Integer, primary_key=True, autoincrement=True),
    Column("transact", Integer, ForeignKey("journal.transact"), nullable=False),
    Column("memo_date", Date, nullable=False),
    Column("memo", Text, nullable=False),
)

recurring_entries = Table(
    "recurring_entries", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("description", String(200), nullable=False),
    Column("debit_account", Integer, ForeignKey("chart.account"), nullable=False),
    Column("credit_account", Integer, ForeignKey("chart.account"), nullable=False),
    Column("amount", Money, nullable=False),
    Column("frequency", String(10), nullable=False),
    Column("day", Integer),  # day of month for monthly entries (clamped to month end)
    Column("next_run", Date, nullable=False),
    Column("end_date", Date),
    Column("active", Boolean, nullable=False, default=True),
    CheckConstraint("frequency IN ('weekly', 'monthly')", name="ck_recurring_frequency"),
    CheckConstraint("amount > 0", name="ck_recurring_amount_positive"),
)

# Accounts every set-up needs. 100-500 are the original system accounts from
# AccountDB.createAccounts; 130/135/230/240 support accruals.
SYSTEM_ACCOUNTS = [
    (100, "ASSETS", "DEBIT"),
    (120, "RECEIVABLES", "DEBIT"),
    (130, "PREPAID EXPENSES", "DEBIT"),
    (135, "ACCRUED REVENUE", "DEBIT"),
    (200, "LIABILITIES", "CREDIT"),
    (220, "PAYABLES", "CREDIT"),
    (230, "ACCRUED EXPENSES", "CREDIT"),
    (240, "DEFERRED REVENUE", "CREDIT"),
    (300, "EQUITY", "CREDIT"),
    (399, "RETAINED EARNINGS", "CREDIT"),
    (400, "REVENUE", "CREDIT"),
    (500, "EXPENSES", "DEBIT"),
]
