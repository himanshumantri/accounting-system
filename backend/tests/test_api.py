import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(engine):
    with TestClient(app) as c:  # lifespan runs init_db against the test engine
        yield c


def test_health_and_system_accounts(client):
    assert client.get("/health").json() == {"status": "ok"}
    accounts = {a["account"] for a in client.get("/chart").json()}
    assert {100, 120, 130, 135, 200, 220, 230, 240, 300, 399, 400, 500} <= accounts


def test_journal_entry_gets_automatic_transaction_numbers(client):
    client.post("/chart", json={"account": 110, "name": "BANK", "type": "DEBIT"})
    ids = []
    for amt in ("10.00", "20.00"):
        r = client.post("/journal", json={"description": "x", "amount": amt, "debit_account": 110,
                                          "credit_account": 300, "entry_date": "2024-01-01"})
        assert r.status_code == 201
        ids.append(r.json()["transact"])
    assert ids == [1, 2]
    assert client.get("/ledger/110").json()["entries"][-1]["balance"] == 30.0


def test_validation_errors_are_clear(client):
    bad = client.post("/journal", json={"description": "x", "amount": "5", "debit_account": 500,
                                        "credit_account": 999})
    assert bad.status_code == 404
    same = client.post("/journal", json={"description": "x", "amount": "5", "debit_account": 500,
                                         "credit_account": 500})
    assert same.status_code == 400
    neg = client.post("/journal", json={"description": "x", "amount": "-5", "debit_account": 500,
                                        "credit_account": 220})
    assert neg.status_code == 422
    dup = client.post("/chart", json={"account": 500, "name": "dup", "type": "DEBIT"})
    assert dup.status_code == 409


def test_accrual_flow_over_http(client):
    r = client.post("/journal", json={
        "description": "March electricity", "amount": "125.12", "debit_account": 500,
        "entry_date": "2024-03-31",
        "accrual": {"type": "accrued_expense", "period_end": "2024-03-31", "auto_reverse": True}})
    assert r.status_code == 201, r.text
    drafts = client.get("/accruals/drafts").json()
    assert len(drafts) == 2
    assert client.get("/reports/trial-balance").json()["total_debits"] == 0
    ids = [d["transact"] for d in drafts]
    assert client.post("/accruals/post-selected", json={"transacts": ids}).status_code == 200
    assert client.post(f"/accruals/drafts/{ids[0]}/post").status_code == 409
    assert client.get("/accruals/drafts").json() == []
    assert client.get("/reports/trial-balance").json()["balanced"] is True


def test_post_selected_is_all_or_nothing(client):
    client.post("/journal", json={
        "description": "x", "amount": "10", "debit_account": 500, "entry_date": "2024-03-31",
        "accrual": {"type": "accrued_expense", "period_end": "2024-03-31"}})
    (draft,) = client.get("/accruals/drafts").json()
    r = client.post("/accruals/post-selected", json={"transacts": [draft["transact"], 9999]})
    assert r.status_code == 404
    assert len(client.get("/accruals/drafts").json()) == 1  # nothing was posted


def test_recurring_over_http_and_token(client, monkeypatch):
    r = client.post("/recurring", json={"description": "Rent", "debit_account": 500, "credit_account": 220,
                                        "amount": "100", "frequency": "monthly", "first_run": "2020-01-15"})
    assert r.status_code == 201
    monkeypatch.setenv("RECURRING_RUN_TOKEN", "s3cret")
    assert client.post("/recurring/run").status_code == 403
    assert client.post("/recurring/run", headers={"X-Run-Token": "wrong"}).status_code == 403
    ok = client.post("/recurring/run", headers={"X-Run-Token": "s3cret"})
    assert ok.status_code == 200 and len(ok.json()["posted"]) > 12
    assert client.post("/recurring/run-now").json()["posted"] == []  # already caught up
    monkeypatch.delenv("RECURRING_RUN_TOKEN")
    assert client.post("/recurring/run", headers={"X-Run-Token": ""}).status_code == 403


def test_memos(client):
    t = client.post("/journal", json={"description": "x", "amount": "1", "debit_account": 500,
                                      "credit_account": 220}).json()["transact"]
    assert client.post("/memos", json={"transact": t, "memo": "note"}).status_code == 201
    assert client.post("/memos", json={"transact": 999, "memo": "note"}).status_code == 404
    assert len(client.get(f"/memos?transact={t}").json()) == 1
