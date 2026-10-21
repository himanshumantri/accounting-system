"""FastAPI app: thin HTTP layer over the services."""
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import Body, FastAPI, Header, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import db
from .models import accountmemos, journal
from .services import accruals as accrual_svc
from .services import posting, recurring, reports
from .services.posting import AccountingError, NotFound

Amount = Field(gt=0, max_digits=14, decimal_places=2)
# Bounds keep absurd values from reaching the database (Postgres integers are 32-bit).
AccountNo = Annotated[int, Field(ge=1, le=9999)]
RowId = Annotated[int, Field(ge=1, le=2_147_483_647)]


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    yield


app = FastAPI(title="Open Accounting API", lifespan=lifespan)

origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(AccountingError)
async def accounting_error_handler(_request, exc: AccountingError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_request, _exc: IntegrityError):
    # e.g. two requests creating the same account at the same moment
    return JSONResponse(status_code=409, content={"detail": "That conflicts with existing data. Please retry."})


# ---------------------------------------------------------------- schemas

class AccountIn(BaseModel):
    account: AccountNo
    name: str
    type: Literal["DEBIT", "CREDIT"]


class AccrualIn(BaseModel):
    type: Literal["accrued_expense", "accrued_revenue", "prepaid_expense", "deferred_revenue"]
    recognition_account: AccountNo | None = None
    period_end: date | None = None
    months: int | None = None
    auto_reverse: bool = False


class JournalIn(BaseModel):
    entry_date: date = Field(default_factory=date.today)
    description: str
    amount: Decimal = Amount
    debit_account: AccountNo | None = None
    credit_account: AccountNo | None = None
    accrual: AccrualIn | None = None


class MemoIn(BaseModel):
    transact: RowId
    memo: str = Field(min_length=1)
    memo_date: date = Field(default_factory=date.today)


class RecurringIn(BaseModel):
    description: str
    debit_account: AccountNo
    credit_account: AccountNo
    amount: Decimal = Amount
    frequency: Literal["weekly", "monthly"]
    first_run: date
    end_date: date | None = None


class PostSelectedIn(BaseModel):
    transacts: list[RowId] = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    with db.engine.connect() as conn:
        conn.execute(select(1))
    return {"status": "ok"}


@app.get("/chart")
def get_chart():
    with db.engine.connect() as conn:
        return reports.list_chart(conn)


@app.post("/chart", status_code=201)
def add_chart_account(body: AccountIn):
    with db.engine.begin() as conn:
        posting.add_account(conn, account=body.account, name=body.name, acct_type=body.type)
    return {"account": body.account}


@app.get("/journal")
def get_journal(status: Literal["all", "posted", "draft"] = "all", start: date | None = None,
                end: date | None = None, limit: Annotated[int, Query(ge=1, le=2000)] = 500):
    """Newest first, at most `limit` entries."""
    stmt = select(journal).order_by(journal.c.entry_date.desc(), journal.c.transact.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(journal.c.posted.is_(status == "posted"))
    if start:
        stmt = stmt.where(journal.c.entry_date >= start)
    if end:
        stmt = stmt.where(journal.c.entry_date <= end)
    with db.engine.connect() as conn:
        return [{"transact": r.transact, "date": r.entry_date, "description": r.description,
                 "debit_account": r.debit_account, "credit_account": r.credit_account,
                 "amount": r.amount, "posted": r.posted, "accrual_id": r.accrual_id} for r in conn.execute(stmt)]


@app.post("/journal", status_code=201)
def add_journal_entry(body: JournalIn):
    with db.engine.begin() as conn:
        if body.accrual is None:
            if body.debit_account is None or body.credit_account is None:
                raise AccountingError("debit_account and credit_account are required.")
            transact = posting.record_entry(
                conn, entry_date=body.entry_date, description=body.description,
                debit_account=body.debit_account, credit_account=body.credit_account, amount=body.amount)
            return {"transact": transact}
        return accrual_svc.create_accrual(
            conn, type=body.accrual.type, description=body.description, amount=body.amount,
            entry_date=body.entry_date, debit_account=body.debit_account, credit_account=body.credit_account,
            recognition_account=body.accrual.recognition_account, period_end=body.accrual.period_end,
            months=body.accrual.months, auto_reverse=body.accrual.auto_reverse)


@app.get("/ledger/{account}")
def get_ledger(account: Annotated[int, Path(ge=1, le=9999)]):
    with db.engine.connect() as conn:
        return reports.ledger_account(conn, account)


@app.get("/memos")
def get_memos(transact: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
              limit: Annotated[int, Query(ge=1, le=2000)] = 500):
    stmt = (select(accountmemos).order_by(accountmemos.c.memo_date.desc(), accountmemos.c.memo_id.desc())
            .limit(limit))
    if transact is not None:
        stmt = stmt.where(accountmemos.c.transact == transact)
    with db.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


@app.post("/memos", status_code=201)
def add_memo(body: MemoIn):
    with db.engine.begin() as conn:
        if conn.execute(select(journal.c.transact).where(journal.c.transact == body.transact)).first() is None:
            raise NotFound(f"Journal entry {body.transact} not found.")
        result = conn.execute(accountmemos.insert().values(
            transact=body.transact, memo_date=body.memo_date, memo=body.memo.strip()))
        return {"memo_id": result.inserted_primary_key[0]}


@app.get("/reports/trial-balance")
def trial_balance():
    with db.engine.connect() as conn:
        return reports.trial_balance(conn)


@app.get("/reports/balance-sheet")
def balance_sheet():
    with db.engine.connect() as conn:
        return reports.balance_sheet(conn)


@app.get("/reports/income-statement")
def income_statement():
    with db.engine.connect() as conn:
        return reports.income_statement(conn)


# ---- recurring entries

@app.get("/recurring")
def list_recurring():
    with db.engine.connect() as conn:
        return recurring.list_all(conn)


@app.post("/recurring", status_code=201)
def add_recurring(body: RecurringIn):
    with db.engine.begin() as conn:
        rec_id = recurring.create(
            conn, description=body.description, debit_account=body.debit_account,
            credit_account=body.credit_account, amount=body.amount, frequency=body.frequency,
            first_run=body.first_run, end_date=body.end_date)
    return {"id": rec_id}


@app.post("/recurring/{rec_id}/active")
def set_recurring_active(rec_id: Annotated[int, Path(ge=1, le=2_147_483_647)], active: bool = Body(embed=True)):
    with db.engine.begin() as conn:
        recurring.set_active(conn, rec_id, active)
    return {"id": rec_id, "active": active}


@app.post("/recurring/run-now")
def run_recurring_now():
    """Used by the UI's 'Run due now' button."""
    return recurring.run_due()


@app.post("/recurring/run")
def run_recurring_scheduled(x_run_token: str | None = Header(default=None)):
    """Called by the scheduled GitLab pipeline. Requires RECURRING_RUN_TOKEN to be set and sent."""
    expected = os.environ.get("RECURRING_RUN_TOKEN")
    if not expected or not secrets.compare_digest((x_run_token or "").encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid or missing run token.")
    return recurring.run_due()


# ---- accrual drafts

@app.get("/accruals/drafts")
def get_accrual_drafts():
    with db.engine.connect() as conn:
        return accrual_svc.list_drafts(conn)


@app.post("/accruals/drafts/{transact}/post")
def post_accrual_draft(transact: Annotated[int, Path(ge=1, le=2_147_483_647)]):
    with db.engine.begin() as conn:
        posting.post_draft(conn, transact)
    return {"transact": transact, "posted": True}


@app.post("/accruals/post-selected")
def post_selected_drafts(body: PostSelectedIn):
    """All-or-nothing: if any draft cannot be posted, none are."""
    with db.engine.begin() as conn:
        for transact in sorted(set(body.transacts)):
            posting.post_draft(conn, transact)
    return {"posted": sorted(set(body.transacts))}


@app.delete("/accruals/drafts/{transact}")
def discard_accrual_draft(transact: Annotated[int, Path(ge=1, le=2_147_483_647)]):
    with db.engine.begin() as conn:
        posting.discard_draft(conn, transact)
    return {"transact": transact, "discarded": True}


@app.delete("/accruals/{accrual_id}")
def discard_accrual(accrual_id: Annotated[int, Path(ge=1, le=2_147_483_647)]):
    with db.engine.begin() as conn:
        count = accrual_svc.discard_accrual(conn, accrual_id)
    return {"accrual_id": accrual_id, "discarded_drafts": count}
