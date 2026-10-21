# Open Accounting: web version

`backend/` (FastAPI, runs on Google Cloud Run) and `frontend/` (React + Vite, published with GitLab Pages)
replace the Tkinter desktop app. The database is a free Neon Postgres. GitLab builds, tests and deploys everything;
Google Cloud only runs the API. The desktop files in the repo root are kept for reference and are not used by the web app.

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

## Deploy (GitLab + Cloud Run + Neon)

| Piece | Where | Notes |
|---|---|---|
| Code, tests, builds, deploys | GitLab CI (`.gitlab-ci.yml`) | Tests run on SQLite and on a Postgres service container. |
| Frontend | GitLab Pages | Free static hosting. Built by the `pages` job. |
| API | Google Cloud Run | Scales to zero; the first request after idle is slow. |
| API container image | Google Artifact Registry | Cloud Run can only pull images from Google's registries. A cleanup policy keeps just the last 2. |
| Database | Neon (free Postgres) | Cloud Run connects over the internet with SSL. |
| Secrets and settings | GitLab CI/CD variables | Passed to Cloud Run as environment variables at deploy time. |

Not used, so they cannot add cost: Cloud Build, Secret Manager, Cloud Scheduler, Firebase. Only two Google APIs
are enabled (Cloud Run and Artifact Registry). Replace `PROJECT_ID`, `REGION` (e.g. `asia-south1`) and the other
capitalised placeholders. You need the [gcloud CLI](https://cloud.google.com/sdk/docs/install) and a Google Cloud
project with billing enabled (the free allowances still need a billing account). Check current pricing yourself.

### 1. Database (Neon)
Create a project at neon.tech. In **Connect**, turn on **Connection pooling** and copy the connection string; its
host contains `-pooler` and it ends in `?sslmode=require`. Tables are created automatically on the first start.

### 2. Google Cloud, one time
```
gcloud auth login
gcloud config set project PROJECT_ID
gcloud services enable run.googleapis.com artifactregistry.googleapis.com
gcloud artifacts repositories create open-accounting --repository-format=docker --location=REGION
gcloud artifacts repositories set-cleanup-policies open-accounting --location=REGION --policy=deploy/artifact-registry-cleanup.json --no-dry-run
```
(If gcloud rejects a flag on the last command, see `gcloud artifacts repositories set-cleanup-policies --help`.)

Create a service account for GitLab to deploy with:
```
gcloud iam service-accounts create gitlab-deployer --display-name "GitLab deployer"
gcloud projects add-iam-policy-binding PROJECT_ID --member "serviceAccount:gitlab-deployer@PROJECT_ID.iam.gserviceaccount.com" --role roles/run.admin
gcloud projects add-iam-policy-binding PROJECT_ID --member "serviceAccount:gitlab-deployer@PROJECT_ID.iam.gserviceaccount.com" --role roles/artifactregistry.writer
gcloud iam service-accounts add-iam-policy-binding PROJECT_NUMBER-compute@developer.gserviceaccount.com --member "serviceAccount:gitlab-deployer@PROJECT_ID.iam.gserviceaccount.com" --role roles/iam.serviceAccountUser
gcloud iam service-accounts keys create sa-key.json --iam-account gitlab-deployer@PROJECT_ID.iam.gserviceaccount.com
```
`gcloud projects describe PROJECT_ID --format="value(projectNumber)"` prints the project number. The key file is a
password: paste its contents into GitLab in the next step, then delete `sa-key.json` (it is git-ignored, but do not
leave it around). If your organisation blocks key creation, use Workload Identity Federation with GitLab's OIDC
tokens instead.

### 3. GitLab: variables and Pages
Push this repository to a GitLab project, then add these under **Settings > CI/CD > Variables**:

| Variable | Type | Value |
|---|---|---|
| `GCP_PROJECT_ID` | Variable | your project id |
| `GCP_REGION` | Variable | the region used above |
| `GCP_SA_KEY` | **File** | contents of `sa-key.json` |
| `DATABASE_URL` | Variable, masked + protected | the Neon pooled connection string |
| `CORS_ORIGINS` | Variable | the Pages origin (step 4) |
| `VITE_API_URL` | Variable | the Cloud Run URL (step 4) |
| `RECURRING_RUN_TOKEN` | Variable, masked + protected | optional: a long random string that enables `POST /recurring/run` |
| `APP_TIMEZONE` | Variable | optional, e.g. `Asia/Kolkata`; what "today" means for recurring entries (default UTC) |

"Protected" variables are only available to protected branches, and the default branch is protected by default.
Turn on Pages for the project if your GitLab plan asks (**Deploy > Pages**).

### 4. First deploy
The Cloud Run URL and Pages URL are only known after the first run, so deploy twice:
1. Merge to the default branch (or **Build > Pipelines > Run pipeline**). `deploy-api` and `pages` run; the
   site may not work yet because `CORS_ORIGINS` and `VITE_API_URL` are still empty.
2. Get the API URL: `gcloud run services describe open-accounting-api --region REGION --format "value(status.url)"`.
   Get the site URL from **Deploy > Pages**. Set `VITE_API_URL` to the first and `CORS_ORIGINS` to the origin of the
   second (scheme and host only, no path, e.g. `https://my-project-1a2b3c.gitlab.io`).
3. **Run pipeline** again from the default branch (a manual run builds and deploys everything).
4. Check `API_URL/health` returns `{"status":"ok"}`, then open the Pages site.

After that, pushes to the default branch redeploy only what changed: `backend/` changes rebuild and redeploy
the API; `frontend/` changes republish the site. Other changes (docs, tests-only) deploy nothing.

### Keeping the Google Cloud bill minimal
- Cloud Run is set to scale to zero (`--min-instances 0`), 512 MiB, at most 2 instances, billed per request.
- Artifact Registry's cleanup policy keeps only the 2 newest images (the first 0.5 GB of storage is free).
- Set a budget alert (**Billing > Budgets & alerts**) at a small amount. Budgets send email but do not stop spending.
- Cloud Run settings are visible to anyone with access to your Google Cloud project, including `DATABASE_URL`.
  If other people get project access, move the secrets to Secret Manager (which has a small free tier).

### Recurring entries
Entries post when someone presses **Run due now** on the Recurring tab. To make it automatic, schedule a call
yourself (for example a GitLab pipeline schedule with its own job; pipelines started by a schedule skip all the
deploy jobs here): `POST API_URL/recurring/run` with the header `X-Run-Token: <RECURRING_RUN_TOKEN>`. It is safe to
call repeatedly: running twice never double-posts and missed periods are caught up.

### Notes
- There is no login yet: anyone with the URL can read and change the data. Use test data only until one is added.
- Cloud Run scales to zero and Neon's free compute pauses when idle, so the first request after a quiet period can
  take several seconds.
- The CI deploy pipeline has not been run end to end: expect to fix small things on the first deploy.

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
- **Recurring entries**: due entries post when you press "Run due now" or when something you schedule calls
  `POST /recurring/run`. Running twice never double-posts, and periods missed because nothing ran are caught up.
  Pausing and resuming skips the paused periods. One run posts at most 400 entries per recurring entry (press the
  button again, or let the next scheduled run continue).
- Reports count contra accounts (e.g. accumulated depreciation, owner drawings) as negatives in their section.
- Reports have no date filter yet and include every posted entry, even one dated in the future, so post drafts when
  their dates arrive.
