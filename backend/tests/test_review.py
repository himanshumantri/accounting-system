"""Edge cases found while reviewing the logic."""
import threading
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import chart, journal
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


@pytest.fixture()
def client(engine):
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ reports

def test_contra_accounts_reduce_their_section_total(engine):
    """Accumulated depreciation is a CREDIT account in the asset range: it must subtract from assets."""
    with engine.begin() as c:
        posting.add_account(c, account=110, name="BANK", acct_type="DEBIT")
        posting.add_account(c, account=140, name="EQUIPMENT", acct_type="DEBIT")
        posting.add_account(c, account=150, name="ACCUM DEPRECIATION", acct_type="CREDIT")
        posting.add_account(c, account=310, name="DRAWINGS", acct_type="DEBIT")
        for dr, cr, amt in [(110, 300, "1000"), (140, 110, "600"), (500, 150, "100"), (310, 110, "50")]:
            posting.record_entry(c, entry_date=date.today(), description="x", debit_account=dr,
                                 credit_account=cr, amount=amt)
    with engine.connect() as c:
        bs = reports.balance_sheet(c)
        assert bs["total_assets"] == D("850.00")        # 350 bank + 600 equipment - 100 contra
        assert bs["total_equity"] == D("850.00")        # 1000 - 50 drawings - 100 net loss
        assert bs["balanced"] is True
        assert reports.trial_balance(c)["balanced"] is True


# ------------------------------------------------------------------ accrual maths

@pytest.mark.parametrize("amount,months", [("100.00", 3), ("1000.00", 12), ("1.00", 100), ("99.99", 7),
                                           ("0.50", 50), ("12345.67", 120)])
def test_split_parts_are_positive_and_sum_exactly(amount, months):
    parts = accruals.split_evenly(D(amount), months)
    assert len(parts) == months and all(p > 0 for p in parts) and sum(parts) == D(amount)


@pytest.mark.parametrize("amount,months", [("0.01", 12), ("1.00", 120)])
def test_amount_too_small_to_spread_is_rejected_cleanly(books, amount, months):
    with pytest.raises(AccountingError, match="too small"):
        with books.begin() as c:
            accruals.create_accrual(c, type="prepaid_expense", description="tiny", amount=amount,
                                    entry_date=date(2024, 1, 1), debit_account=130, credit_account=110,
                                    recognition_account=510, months=months)
    with books.connect() as c:  # nothing half-created
        assert c.execute(select(func.count()).select_from(journal)).scalar_one() == 1


# ------------------------------------------------------------------ draft ordering

def test_reversal_cannot_be_posted_before_its_original_and_discard_cascades(books):
    with books.begin() as c:
        res = accruals.create_accrual(c, type="accrued_expense", description="Power", amount="50",
                                      entry_date=date(2024, 3, 31), debit_account=500,
                                      period_end=date(2024, 3, 31), auto_reverse=True)
        original, reversal = res["draft_transacts"]
    with pytest.raises(Conflict, match="first"):
        with books.begin() as c:
            posting.post_draft(c, reversal)
    with books.begin() as c:
        posting.post_draft(c, original)
        posting.post_draft(c, reversal)  # fine once the original is posted
        assert bal(c, 500) == D("0.00")
    with books.begin() as c:
        res = accruals.create_accrual(c, type="accrued_expense", description="Water", amount="20",
                                      entry_date=date(2024, 3, 31), debit_account=500,
                                      period_end=date(2024, 3, 31), auto_reverse=True)
        posting.discard_draft(c, res["draft_transacts"][0])  # discarding the original drops its reversal
        assert accruals.list_drafts(c) == []


def test_monthly_drafts_wait_for_the_prepaid_entry(books):
    with books.begin() as c:
        res = accruals.create_accrual(c, type="prepaid_expense", description="Cover", amount="120",
                                      entry_date=date(2024, 1, 1), debit_account=130, credit_account=110,
                                      recognition_account=510, months=3)
        source, first_month = res["draft_transacts"][:2]
    with pytest.raises(Conflict, match="first"):
        with books.begin() as c:
            posting.post_draft(c, first_month)
    with books.begin() as c:
        posting.post_draft(c, source)
        posting.post_draft(c, first_month)


def test_post_selected_orders_by_dependency(client):
    client.post("/journal", json={
        "description": "x", "amount": "10", "debit_account": 500, "entry_date": "2024-03-31",
        "accrual": {"type": "accrued_expense", "period_end": "2024-03-31", "auto_reverse": True}})
    ids = [d["transact"] for d in client.get("/accruals/drafts").json()]
    assert client.post("/accruals/post-selected", json={"transacts": ids[::-1]}).status_code == 200


# ------------------------------------------------------------------ recurring

def test_resuming_does_not_backfill_the_paused_period(books):
    with books.begin() as c:
        rid = recurring.create(c, description="Rent", debit_account=500, credit_account=110, amount="100",
                               frequency="monthly", first_run=date(2024, 1, 15))
    recurring.run_due(date(2024, 1, 15))
    with books.begin() as c:
        recurring.set_active(c, rid, False)
    with books.begin() as c:
        recurring.set_active(c, rid, True, today=date(2024, 5, 20))
    result = recurring.run_due(date(2024, 5, 20))
    assert result["posted"] == []                     # Feb-May skipped while paused
    result = recurring.run_due(date(2024, 6, 15))
    assert [p["date"] for p in result["posted"]] == [date(2024, 6, 15)]


def test_run_is_capped_per_entry_and_resumes_next_time(books):
    with books.begin() as c:
        recurring.create(c, description="Weekly", debit_account=500, credit_account=110, amount="1",
                         frequency="weekly", first_run=date(2000, 1, 1))
    first = recurring.run_due(date(2024, 1, 1))
    assert len(first["posted"]) == recurring.MAX_PER_RUN and first["truncated"] is True
    second = recurring.run_due(date(2024, 1, 1))
    assert len(second["posted"]) > 0


def test_concurrent_runs_never_double_post(books):
    if books.dialect.name != "postgresql":
        pytest.skip("row locking is a Postgres behaviour; SQLite serialises writers differently")
    with books.begin() as c:
        recurring.create(c, description="Rent", debit_account=500, credit_account=110, amount="100",
                         frequency="monthly", first_run=date(2024, 1, 1))
    results = []
    threads = [threading.Thread(target=lambda: results.append(recurring.run_due(date(2024, 12, 31))))
               for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(len(r["posted"]) for r in results) == 12
    with books.connect() as c:
        assert bal(c, 500) == D("1200.00")


# ------------------------------------------------------------------ API robustness

@pytest.mark.parametrize("method,url,body", [
    ("get", "/ledger/99999999999", None),
    ("get", "/memos?transact=99999999999", None),
    ("post", "/accruals/drafts/99999999999/post", None),
    ("delete", "/accruals/drafts/99999999999", None),
    ("delete", "/accruals/99999999999", None),
    ("post", "/recurring/99999999999/active", {"active": False}),
    ("post", "/memos", {"transact": 99999999999, "memo": "x"}),
    ("post", "/journal", {"description": "x", "amount": "1", "debit_account": 99999999999, "credit_account": 220}),
])
def test_out_of_range_ids_give_4xx_not_500(client, method, url, body):
    r = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert 400 <= r.status_code < 500, r.text


def test_journal_listing_is_limited(client):
    for _ in range(3):
        client.post("/journal", json={"description": "x", "amount": "1", "debit_account": 500,
                                      "credit_account": 220})
    assert len(client.get("/journal?limit=2").json()) == 2
    assert client.get("/journal?limit=0").status_code == 422


def test_duplicate_account_race_is_a_409_not_a_500(client, monkeypatch):
    """Two requests passing the exists-check at once should still end in a clean 409."""
    monkeypatch.setattr(posting, "_account_exists", lambda *_a, **_k: False)
    assert client.post("/chart", json={"account": 510, "name": "A", "type": "DEBIT"}).status_code == 201
    assert client.post("/chart", json={"account": 510, "name": "B", "type": "DEBIT"}).status_code == 409
