from decimal import Decimal

import pytest

from app import seed
from app.services import reports

D = Decimal


@pytest.fixture()
def seeded(engine):
    seed.seed()
    with engine.connect() as c:
        yield c


def by_account(rows):
    return {r["account"]: r["balance"] for r in rows}


def test_seed_matches_the_old_sample_balances(seeded):
    chart = {r["account"]: r["balance"] for r in reports.list_chart(seeded)}
    assert chart[110] == D("903.19")
    assert chart[120] == D("100.00")
    assert chart[500] == D("94.69")
    assert chart[520] == D("125.12")
    assert chart[220] == D("0.00")


def test_trial_balance_debits_equal_credits(seeded):
    tb = reports.trial_balance(seeded)
    assert tb["total_debits"] == D("1223.00")
    assert tb["total_credits"] == D("1223.00")
    assert tb["balanced"] is True
    assert tb["mismatches"] == []


def test_income_statement_matches_known_figures(seeded):
    inc = reports.income_statement(seeded)
    assert inc["total_revenue"] == D("223.00")
    assert inc["total_expenses"] == D("219.81")
    assert inc["net_income"] == D("3.19")


def test_balance_sheet_balances_and_shows_retained_earnings_once(seeded):
    bs = reports.balance_sheet(seeded)
    assert bs["total_assets"] == D("1003.19")
    assert bs["total_liabilities"] == D("0.00")
    assert bs["total_equity"] == D("1003.19")
    assert bs["balanced"] is True
    assert [r["account"] for r in bs["equity"]].count(399) == 1
    assert by_account(bs["equity"])[399] == D("3.19")


def test_liabilities_are_reported_in_liabilities_not_assets(engine):
    from datetime import date
    from app.services import posting
    with engine.begin() as c:
        posting.record_entry(c, entry_date=date.today(), description="bill", debit_account=500,
                             credit_account=220, amount="50.00")
    with engine.connect() as c:
        bs = reports.balance_sheet(c)
    assert bs["total_liabilities"] == D("50.00")
    assert bs["total_assets"] == D("0.00")
    assert bs["total_equity"] == D("-50.00")
    assert bs["balanced"] is True


def test_ledger_account_report(seeded):
    led = reports.ledger_account(seeded, 110)
    assert led["name"] == "BANK"
    assert led["entries"][-1]["balance"] == D("903.19")
    assert all(e["description"] for e in led["entries"])
