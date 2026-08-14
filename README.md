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
web/                    React, routes per product
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

API (after Postgres is up):

```powershell
$env:PYTHONPATH = "packages/foundation;packages/canonical;packages/ingest;packages/rules;apps/pulse;apps/api"
uvicorn app.main:app --reload --app-dir apps/api
```

## Workflow

One branch per spec section. Independently testable.

```
git checkout -b feat/schema
git checkout -b feat/csv-importer
git checkout -b feat/identity-resolution
git checkout -b feat/rule-dup-exact
```

Work, commit, push, PR, merge. Do not commit on `main`.

## India then Dubai

Same image. `docker/india.env.example` vs `docker/uae.env.example`. Region is `ap-south-1` then `me-central-1`.
