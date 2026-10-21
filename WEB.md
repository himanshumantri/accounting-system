# Open Accounting: web version

`backend/` (FastAPI, runs on Google Cloud Run) and `frontend/` (React + Vite, served by Firebase Hosting)
replace the Tkinter desktop app. The database is a free Neon Postgres. The desktop files in the repo root are kept for reference and are not used by the web app.

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

## Deploy (Google Cloud + Neon)

| Piece | Service | Notes |
|---|---|---|
| Database | Neon (free Postgres) | Outside Google Cloud; Cloud Run connects to it over the internet with SSL. |
| API | Cloud Run | Container built from `backend/Dockerfile`. Scales to zero, so the first request after idle is slow. |
| Frontend | Firebase Hosting | Static files from `frontend/dist`. |
| Recurring entries | Cloud Scheduler | Calls `POST /recurring/run` every night. |
| Secrets | Secret Manager | Holds `DATABASE_URL` and `RECURRING_RUN_TOKEN`. |

Replace `PROJECT_ID`, `REGION` (e.g. `asia-south1`) and the other capitalised placeholders below. You need the
[gcloud CLI](https://cloud.google.com/sdk/docs/install) and a Google Cloud project with billing enabled (the free
allowances still require a billing account). Check current pricing and free-tier limits before you rely on them.

### 1. Database (Neon)
Create a project at neon.tech. In **Connect**, turn on **Connection pooling** and copy the connection string; its
host contains `-pooler` and it ends in `?sslmode=require`. Tables are created automatically on the first start.

### 2. Google Cloud setup and secrets
```
gcloud auth login
gcloud config set project PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com
```
Put the Neon connection string alone in a text file (`neon-url.txt`) and a random token in another
(`python -c "import secrets; print(secrets.token_urlsafe(32))"` generates one), then:
```
gcloud secrets create database-url --data-file=neon-url.txt
gcloud secrets create recurring-run-token --data-file=token.txt
```
Delete both text files afterwards. Let Cloud Run read the secrets (its default service account is
`PROJECT_NUMBER-compute@developer.gserviceaccount.com`; `gcloud projects describe PROJECT_ID --format="value(projectNumber)"`
prints the number):
```
gcloud secrets add-iam-policy-binding database-url --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding recurring-run-token --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
```

### 3. API on Cloud Run
```
gcloud run deploy open-accounting-api --source backend --region REGION --allow-unauthenticated --max-instances 3 --set-secrets "DATABASE_URL=database-url:latest,RECURRING_RUN_TOKEN=recurring-run-token:latest" --set-env-vars "CORS_ORIGINS=https://PROJECT_ID.web.app,APP_TIMEZONE=Asia/Kolkata"
```
- Answer **Y** if it offers to create an Artifact Registry repository.
- `--allow-unauthenticated` is needed because browsers call the API directly. There is no login yet.
- `CORS_ORIGINS` is the Firebase Hosting URL from step 4 (`https://PROJECT_ID.web.app`). To allow several
  origins, separate them with commas and use a different list delimiter for the flag, for example
  `--set-env-vars "^@^CORS_ORIGINS=https://PROJECT_ID.web.app,https://PROJECT_ID.firebaseapp.com@APP_TIMEZONE=Asia/Kolkata"`.
- `APP_TIMEZONE` sets what "today" means for recurring entries; Cloud Run itself runs in UTC.
- The command prints the service URL (`https://open-accounting-api-XXXX.REGION.run.app`). Check
  `curl SERVICE_URL/health` returns `{"status":"ok"}`.

### 4. Frontend on Firebase Hosting
Add Firebase to the project once (console.firebase.google.com, "Add project", pick your existing project), then:
```
cd frontend
npm install
```
Build with the API URL set (it is baked in at build time):
- PowerShell: `$env:VITE_API_URL="SERVICE_URL"; npm run build`
- bash: `VITE_API_URL=SERVICE_URL npm run build`
```
npx firebase-tools login
npx firebase-tools use --add          # choose PROJECT_ID
npx firebase-tools deploy --only hosting
```
It prints the site URL (`https://PROJECT_ID.web.app`). If it differs from what you put in `CORS_ORIGINS`,
update the Cloud Run variable: `gcloud run services update open-accounting-api --region REGION --update-env-vars ...`.

### 5. Recurring entries (Cloud Scheduler)
```
gcloud scheduler jobs create http recurring-entries --location REGION --schedule "0 2 * * *" --time-zone "Asia/Kolkata" --uri "SERVICE_URL/recurring/run" --http-method POST --headers "X-Run-Token=YOUR_TOKEN" --attempt-deadline 180s --max-retry-attempts 3
gcloud scheduler jobs run recurring-entries --location REGION      # test it now
```
`YOUR_TOKEN` is the value in `recurring-run-token`
(`gcloud secrets versions access latest --secret recurring-run-token`).

### Redeploying
API: rerun the `gcloud run deploy` command (the flags are remembered, so `gcloud run deploy open-accounting-api --source backend --region REGION` is enough).
Frontend: rebuild, then `npx firebase-tools deploy --only hosting`.

### Things to know
- There is no login yet: anyone with the URL can read and change the data. Use test data only until one is added.
- Cloud Run scales to zero and Neon's free compute pauses when idle, so the first request after a quiet period can
  take several seconds. The nightly scheduler call retries to cover this.
- To change the database later, only the `database-url` secret changes (`gcloud secrets versions add database-url --data-file=...`, then redeploy).

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
- **Recurring entries**: due entries post when you press "Run due now" or when Cloud Scheduler calls
  `POST /recurring/run`. Running twice never double-posts, and periods missed because nothing ran are caught up.
  Pausing and resuming skips the paused periods. One run posts at most 400 entries per recurring entry (press the
  button again, or let the next scheduled run continue).
- Reports count contra accounts (e.g. accumulated depreciation, owner drawings) as negatives in their section.
- Reports have no date filter yet and include every posted entry, even one dated in the future, so post drafts when
  their dates arrive.
