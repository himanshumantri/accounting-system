# Open Accounting: web version

`backend/` (FastAPI, deploy to Render) and `frontend/` (React + Vite, deploy to Vercel) replace the
Tkinter desktop app. The desktop files in the repo root are kept for reference and are not used by the web app.

## Run locally

```
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Windows
.venv/Scripts/python -m app.seed          # optional demo data (the old sample books)
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
.venv/Scripts/python -m pytest -q         # tests (SQLite)
# Same tests on Postgres (use a throwaway database: its tables are dropped first):
TEST_DATABASE_URL=postgresql://user:pass@localhost/testdb .venv/Scripts/python -m pytest -q

cd ../frontend
npm install
npm run dev                               # http://localhost:5173
```

Without `DATABASE_URL` the API uses a local SQLite file (`openaccounting.db`, git-ignored). Tables are created
on start but never altered, so delete any old local `openaccounting.db` after pulling schema changes.

## Deploy

1. **Database**: create a free Postgres (e.g. Neon) and copy its connection string.
2. **Render**: create a Blueprint from `render.yaml`; set `DATABASE_URL`, `CORS_ORIGINS` (your Vercel URL),
   `RECURRING_RUN_TOKEN` (a long random string). Tables are created on first start.
3. **Vercel**: import the repo with root directory `frontend`; set `VITE_API_URL` to the Render URL.
4. **Recurring entries**: add `API_URL` and `RECURRING_RUN_TOKEN` as masked GitLab CI/CD variables, then a
   daily pipeline schedule (see `.gitlab-ci.yml`).

There is no login yet: anyone with the URL can read and change the data. Use test data only until one is added.
Render's free web tier sleeps when idle, so the first request after a pause can take about a minute.

## How the books work

- A journal entry is one debit and one credit of the same positive amount. Transaction numbers are automatic.
- Opening balances go through the journal (new accounts always open at zero), so debits always equal credits.
- Accounts are numbered 100-699: 1xx assets, 2xx liabilities, 3xx equity, 4xx revenue, 5xx-6xx expenses.
- **Accruals**: tick "Accrual" on the entry form. Accrued expense/revenue create a draft on the period end date
  (plus an optional reversal the next day); prepaid/deferred create a draft of the entry itself plus a draft for
  each month of amortization. Every accrual entry is a draft: nothing reaches the ledger or reports until you
  post it manually on the Accruals tab.
- Accrual drafts keep their order: a reversal can only be posted after its original, and monthly amortization
  after the prepaid/deferred entry (discarding an entry also discards the drafts that depend on it). Monthly
  amounts are rounded down to the cent with the remainder in the last month.
- **Recurring entries**: due entries post when you press "Run due now" or when the scheduled pipeline calls
  `POST /recurring/run`. Running twice never double-posts, and periods missed because nothing ran are caught up.
  Pausing and resuming skips the paused periods. One run posts at most 400 entries per recurring entry (press the
  button again, or let the next scheduled run continue).
- Reports count contra accounts (e.g. accumulated depreciation, owner drawings) as negatives in their section.
- Reports have no date filter yet and include every posted entry, even one dated in the future, so post drafts when
  their dates arrive.
