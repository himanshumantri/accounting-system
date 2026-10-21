from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import chart, journal, ledger
from app.services import posting
from app.services.posting import AccountingError, Conflict, NotFound

D = Decimal


def add(conn, number, name, kind):
    posting.add_account(conn, account=number, name=name, acct_type=kind)


def balance(conn, account):
    return conn.execute(select(chart.c.balance).where(chart.c.account == account)).scalar_one()


def entry(conn, debit, credit, amount, **kw):
    return posting.record_entry(conn, entry_date=date(2024, 1, 15), description="test",
                                debit_account=debit, credit_account=credit, amount=amount, **kw)


def test_debit_and_credit_amounts_land_on_the_right_accounts(conn):
    add(conn, 110, "BANK", "DEBIT")
    entry(conn, 110, 300, "1000.00")  # Dr bank / Cr equity
    assert balance(conn, 110) == D("1000.00")
    assert balance(conn, 300) == D("1000.00")
    entry(conn, 500, 110, "40.50")  # Dr expense / Cr bank: bank goes DOWN, expense UP
    assert balance(conn, 500) == D("40.50")
    assert balance(conn, 110) == D("959.50")


def test_paying_a_payable_reduces_both_sides(conn):
    add(conn, 110, "BANK", "DEBIT")
    entry(conn, 110, 300, "100.00")
    entry(conn, 500, 220, "10.00")   # bill: expense up, payable up
    entry(conn, 220, 110, "10.00")   # payment: payable down, bank down
    assert balance(conn, 220) == D("0.00")
    assert balance(conn, 110) == D("90.00")


def test_ledger_rows_carry_signed_amount_and_running_balance(conn):
    add(conn, 110, "BANK", "DEBIT")
    entry(conn, 110, 300, "100.00")
    entry(conn, 500, 110, "30.00")
    rows = conn.execute(select(ledger.c.account, ledger.c.amount, ledger.c.balance)
                        .where(ledger.c.account == 110).order_by(ledger.c.id)).all()
    assert [(r.amount, r.balance) for r in rows] == [(D("100.00"), D("100.00")), (D("-30.00"), D("70.00"))]


@pytest.mark.parametrize("amount", ["0", "-5", "abc", "1000000000000"])
def test_bad_amounts_rejected(conn, amount):
    with pytest.raises(AccountingError):
        entry(conn, 500, 220, amount)


def test_same_account_unknown_account_and_blank_description_rejected(conn):
    with pytest.raises(AccountingError):
        entry(conn, 500, 500, "1.00")
    with pytest.raises(NotFound):
        entry(conn, 500, 999, "1.00")
    with pytest.raises(AccountingError):
        posting.record_entry(conn, entry_date=date.today(), description="  ", debit_account=500,
                             credit_account=220, amount="1")


def test_failed_entry_rolls_back_everything(engine):
    with pytest.raises(NotFound):
        with engine.begin() as c:
            posting.record_entry(c, entry_date=date.today(), description="ok", debit_account=500,
                                 credit_account=220, amount="5.00")
            posting.record_entry(c, entry_date=date.today(), description="bad", debit_account=500,
                                 credit_account=999, amount="5.00")
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(journal)).scalar_one() == 0
        assert c.execute(select(func.count()).select_from(ledger)).scalar_one() == 0
        assert balance(c, 500) == D("0.00")


def test_sql_in_description_is_stored_as_text(conn):
    posting.record_entry(conn, entry_date=date.today(), description="x'); DROP TABLE chart;--",
                         debit_account=500, credit_account=220, amount="1.00")
    assert conn.execute(select(func.count()).select_from(chart)).scalar_one() > 0


def test_draft_does_not_touch_ledger_and_posts_exactly_once(conn):
    t = entry(conn, 500, 220, "25.00", posted=False)
    assert balance(conn, 500) == D("0.00")
    assert conn.execute(select(func.count()).select_from(ledger)).scalar_one() == 0
    posting.post_draft(conn, t)
    assert balance(conn, 500) == D("25.00")
    with pytest.raises(Conflict):
        posting.post_draft(conn, t)
    assert balance(conn, 500) == D("25.00")


def test_discard_only_drafts(conn):
    draft = entry(conn, 500, 220, "5.00", posted=False)
    real = entry(conn, 500, 220, "7.00")
    posting.discard_draft(conn, draft)
    with pytest.raises(Conflict):
        posting.discard_draft(conn, real)


def test_add_account_validation(conn):
    with pytest.raises(Conflict):
        add(conn, 500, "dup", "DEBIT")
    with pytest.raises(AccountingError):
        add(conn, 50, "too low", "DEBIT")
    with pytest.raises(AccountingError):
        add(conn, 710, "too high", "DEBIT")
    with pytest.raises(AccountingError):
        add(conn, 510, "x", "SIDEWAYS")
    add(conn, 510, "Rent", "debit")
    assert balance(conn, 510) == D("0.00")
