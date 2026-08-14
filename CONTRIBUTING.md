# How this repo ships

Three lines. Do not invent a fourth.

```
feat/<section>  ──PR──►  staging  ──PR──►  main
   you work              TEST              PRODUCTION
```

`main` is production. `staging` is the test stack. You never commit to either. You open a pull request.

This is the same discipline as Accumo_New, plus a staging line because this repo will hold bank accounts and payment history — not a brochure.

## Branches

| Branch | What it is | Who merges |
|---|---|---|
| `feat/…` | One spec section. Independently testable. | You, via PR into `staging` |
| `fix/…` | A bug. Same rules as feat. | PR into `staging` |
| `staging` | What testers run. Synthetic data only. | PR from feat/fix after CI is green |
| `main` | Production image. Customer stacks deploy from here. | PR **from `staging` only** |

Names match the spec: `feat/csv-importer`, `feat/identity-resolution`, `feat/rule-dup-exact`. Not `ameen-wip` and not `update`.

## Daily loop (a feature)

```powershell
git checkout staging
git pull
git checkout -b feat/csv-importer
# work
python -m pytest
git add -A
git commit -m "Add CSV mapping so a second import does not start from scratch"
git push -u origin feat/csv-importer
```

Open a PR: **base = `staging`**, compare = your branch.

Merge only when:

- CI is green
- The PR template boxes are honest
- You have not added a CSV, XLSX, `.env`, or customer row

After merge, **test on staging**. If it is wrong, fix on another `feat/` or `fix/` into staging. Do not “just push to staging”.

## Promote to production

When staging has been checked:

```powershell
git checkout main
git pull
git checkout -b release/YYYY-MM-DD
# or open a PR directly: staging → main on GitHub
```

Simplest: GitHub → New pull request → base `main` ← compare `staging`.

Title: `Promote staging to production`. Body: what you tested and that no customer data is in the diff.

Merge that PR. Production workflow runs. Tag if you want a name:

```powershell
git checkout main
git pull
git tag -a v0.1.0 -m "First staging-proven cut"
git push origin v0.1.0
```

## What CI does

Every PR into `staging` or `main` runs `pytest` on Python 3.12. Red X = do not merge.

Push to `staging` deploys the **staging** environment (shared test box, `ap-south-1`, synthetic data).

Push to `main` deploys **production** (per-customer stacks later; India `ap-south-1`, UAE `me-central-1`).

Until those boxes exist the deploy jobs are the hook. Do not point them at a laptop.

## What you never do

- Commit on `main` or `staging`
- Force-push `main` or `staging`
- Open a feature PR straight into `main` (skips the test line)
- Merge with failing tests
- Put a real export in git, even “just for a minute”

## GitHub settings (do once, in the browser)

Repo → Settings:

1. **General → Default branch** = `main`
2. Branches → Add rule for `main` and for `staging`:
   - Require a pull request
   - Require status checks: `test`
   - Do not allow bypassing (even for yourself, once you are used to it)
3. Environments → create `staging` and `production`
   - `production`: required reviewers = you, so a merge to main cannot deploy while you sleep by accident

Private stays private.
