from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import chart, journal, ledger
from app.services import accruals, posting, recurring, reports
from app.services.posting import AccountingError, Conflict

D = Decimal


def bal(conn, account):
    return conn.execute(select(chart.c.balance).where(chart.c.account == account)).scalar_one()


@pytest.fixture()
def books(engine):
    with engine.begin() as c:
        posting.add_account(c, account=110, name="BANK", acct_type="DEBIT")
        posting.add_account(c, account=510, name="Insurance", acct_type="DEBIT")
        posting.add_account(c, account=410, name="Consulting", acct_type="CREDIT")
        posting.record_entry(c, entry_date=date(2024, 1, 1), description="start", debit_account=110,
                             credit_account=300, amount="10000.00")
    return engine


# ------------------------------------------------------------------ recurring

def make_rent(engine, first, frequency="monthly", end=None):
    with engine.begin() as c:
        return recurring.create(c, description="Rent", debit_account=500, credit_account=110, amount="100.00",
                                frequency=frequency, first_run=first, end_date=end)


def test_recurring_posts_due_entries_once(books):
    make_rent(books, date(2024, 3, 1))
    first = recurring.run_due(date(2024, 3, 1))
    assert len(first["posted"]) == 1
    again = recurring.run_due(date(2024, 3, 1))  # same day rerun posts nothing
    assert again["posted"] == []
    with books.connect() as c:
        assert bal(c, 500) == D("100.00")


def test_recurring_catches_up_missed_months(books):
    make_rent(books, date(2024, 1, 31))
    result = recurring.run_due(date(2024, 4, 30))
    dates = [p["date"] for p in result["posted"]]
    assert dates == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)]
    with books.connect() as c:
        assert bal(c, 500) == D("400.00")


def test_recurring_respects_end_date_pause_and_weekly(books):
    rid = make_rent(books, date(2024, 1, 1), end=date(2024, 2, 15))
    assert len(recurring.run_due(date(2024, 6, 1))["posted"]) == 2  # Jan 1, Feb 1 only
    rid2 = make_rent(books, date(2024, 1, 1), frequency="weekly")
    with books.begin() as c:
        recurring.set_active(c, rid2, False)
    assert recurring.run_due(date(2024, 6, 1))["posted"] == []
    assert rid != rid2


def test_recurring_validation(books):
    with books.begin() as c:
        with pytest.raises(AccountingError):
            recurring.create(c, description="x", debit_account=500, credit_account=110, amount="1",
                             frequency="daily", first_run=date.today())
        with pytest.raises(AccountingError):
            recurring.create(c, description="x", debit_account=500, credit_account=999, amount="1",
                             frequency="weekly", first_run=date.today())


# ------------------------------------------------------------------ accruals

def test_accrued_expense_with_reversal_is_draft_then_nets_to_zero(books):
    with books.begin() as c:
        res = accruals.create_accrual(c, type="accrued_expense", description="March electricity",
                                      amount="125.12", entry_date=date(2024, 3, 31), debit_account=500,
                                      period_end=date(2024, 3, 31), auto_reverse=True)
        assert len(res["draft_transacts"]) == 2 and res["source_transact"] is None
        assert bal(c, 500) == D("0.00") and bal(c, 230) == D("0.00")  # drafts don't post
        assert reports.trial_balance(c)["total_debits"] == D("10000.00")
        drafts = accruals.list_drafts(c)
        assert [(d["date"], d["debit_account"], d["credit_account"]) for d in drafts] == [
            (date(2024, 3, 31), 500, 230), (date(2024, 4, 1), 230, 500)]
        for t in res["draft_transacts"]:
            posting.post_draft(c, t)
        assert bal(c, 500) == D("0.00") and bal(c, 230) == D("0.00")  # reversal nets it out
        assert accruals.list_drafts(c) == []
        assert c.execute(select(func.count()).select_from(ledger)).scalar_one() == 2 + 4


def test_accrued_revenue_defaults_to_account_135(books):
    with books.begin() as c:
        res = accruals.create_accrual(c, type="accrued_revenue", description="Unbilled work", amount="800.00",
                                      entry_date=date(2024, 6, 30), credit_account=410,
                                      period_end=date(2024, 6, 30))
        (draft,) = accruals.list_drafts(c)
        assert (draft["debit_account"], draft["credit_account"]) == (135, 410)
        posting.post_draft(c, res["draft_transacts"][0])
        assert bal(c, 135) == D("800.00") and bal(c, 410) == D("800.00")


def test_prepaid_is_all_drafts_and_amortizes_without_rounding_drift(books):
    with books.begin() as c:
        res = accruals.create_accrual(c, type="prepaid_expense", description="Annual insurance",
                                      amount="1000.00", entry_date=date(2024, 1, 10), debit_account=130,
                                      credit_account=110, recognition_account=510, months=12)
        assert bal(c, 130) == D("0.00") and bal(c, 110) == D("10000.00")  # nothing posted yet
        drafts = accruals.list_drafts(c)
        assert len(drafts) == 13  # the entry as typed + 12 monthly entries
        assert res["draft_transacts"][0] == res["source_transact"]
        source, months = drafts[0], drafts[1:]
        assert (source["debit_account"], source["credit_account"], source["amount"]) == (130, 110, D("1000.00"))
        assert sum(d["amount"] for d in months) == D("1000.00")
        assert months[0]["date"] == date(2024, 1, 31) and months[-1]["date"] == date(2024, 12, 31)
        assert months[-1]["amount"] != months[0]["amount"]  # last month absorbs the remainder
        for t in res["draft_transacts"]:
            posting.post_draft(c, t)
        assert bal(c, 130) == D("0.00") and bal(c, 110) == D("9000.00") and bal(c, 510) == D("1000.00")


def test_deferred_revenue_recognized_monthly(books):
    with books.begin() as c:
        res = accruals.create_accrual(c, type="deferred_revenue", description="Annual retainer",
                                      amount="600.00", entry_date=date(2024, 1, 5), debit_account=110,
                                      credit_account=240, recognition_account=410, months=3)
        assert bal(c, 240) == D("0.00") and bal(c, 110) == D("10000.00")  # nothing posted yet
        for t in res["draft_transacts"]:
            posting.post_draft(c, t)
        assert bal(c, 240) == D("0.00") and bal(c, 410) == D("600.00") and bal(c, 110) == D("10600.00")


def test_approve_twice_rejected_and_discard_removes_only_drafts(books):
    with books.begin() as c:
        res = accruals.create_accrual(c, type="prepaid_expense", description="Software", amount="120.00",
                                      entry_date=date(2024, 1, 1), debit_account=130, credit_account=110,
                                      recognition_account=510, months=4)
        first = res["draft_transacts"][0]  # the entry as typed
        posting.post_draft(c, first)
        with pytest.raises(Conflict):
            posting.post_draft(c, first)
        removed = accruals.discard_accrual(c, res["accrual_id"])
        assert removed == 4
        assert c.execute(select(journal.c.posted).where(journal.c.transact == first)).scalar_one() is True
        assert c.execute(select(func.count()).select_from(journal).where(
            journal.c.accrual_id == res["accrual_id"])).scalar_one() == 1  # only the posted entry remains


def test_accrual_validation(books):
    with books.begin() as c:
        with pytest.raises(AccountingError):  # reversal makes no sense for prepaid
            accruals.create_accrual(c, type="prepaid_expense", description="x", amount="10", entry_date=date.today(),
                                    debit_account=130, credit_account=110, recognition_account=510, months=2,
                                    auto_reverse=True)
        with pytest.raises(AccountingError):  # accrued expense needs an expense account
            accruals.create_accrual(c, type="accrued_expense", description="x", amount="10", entry_date=date.today(),
                                    debit_account=110, period_end=date.today())
        with pytest.raises(AccountingError):
            accruals.create_accrual(c, type="bogus", description="x", amount="10", entry_date=date.today())


def test_split_evenly_totals_exactly():
    parts = accruals.split_evenly(D("100.00"), 3)
    assert parts == [D("33.33"), D("33.33"), D("33.34")] and sum(parts) == D("100.00")
