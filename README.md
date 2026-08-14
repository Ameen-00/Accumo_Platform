# Accumo platform

Private. Pulse, Atlas and Snip — one repo, one Foundation.

Marketing sites stay where they are (`Accumo_New`, `Accumo_Admin-`). Different deploy, different lifecycle.

## Layout

```
packages/foundation/    evidence, policy versions, audit log, RBAC, auth, crypto
packages/canonical/     shared model + normalise + db
packages/ingest/        CSV mapping, later Odoo
packages/rules/         rule protocol (Pulse and Atlas)
apps/api/               FastAPI — serves every product
apps/pulse/             payment-integrity catalogue + (later) rules
apps/atlas/             later
apps/snip/              later
web/                    Pulse reviewer app (import, findings, pack)
tests/synthetic/        planted exceptions — the only allowed “customer” data
docker/                 compose, Caddy, India / UAE env examples
```

No Nx. No Turborepo. Folders and `PYTHONPATH`.

## Rules that do not bend

- **Never commit customer data.** Synthetic only. `*.csv` and `*.xlsx` are gitignored on purpose.
- **Never commit secrets.** `.env` is ignored from the first commit.
- **Private by default.** This repo is private.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m pytest
python -m tests.synthetic.generate --rows 5000 --country IN --out .data/in
```

Import a file (after sign-in, with Postgres up):

```
POST /imports
POST /imports/{id}/files     entity=payment + the CSV
PUT  /imports/{id}/files/{fid}/map
POST /imports/{id}/commit
POST /runs                       {batch_id}
POST /exceptions/{id}/transition
POST /reports/evidence-pack      {run_id}  → ZIP (PDF + CSVs)
GET  /reports/{id}/download
```

If dates look like `03/07/2026`, the API will refuse to guess. Send `date_format: "dmy"` (India) or `"mdy"`.

API (after Postgres is up):

```powershell
$env:PYTHONPATH = "packages/foundation;packages/canonical;packages/ingest;packages/rules;apps/pulse;apps/api"
uvicorn app.main:app --reload --app-dir apps/api
```

Reviewer app (API already running):

```powershell
cd web
npm install
npm run dev
```

Open http://localhost:5173 — import → run → confirm/dismiss → download pack. This is the product. The page on accumo.co/pulse is only a sales demo.

## Workflow

```
feat/<section>  ──PR──►  staging  ──PR──►  main
                     TEST              PRODUCTION
```

Never commit on `staging` or `main`. Full loop is in [CONTRIBUTING.md](CONTRIBUTING.md).

## India then Dubai

Same image. `docker/india.env.example` vs `docker/uae.env.example`. Region is `ap-south-1` then `me-central-1`.
