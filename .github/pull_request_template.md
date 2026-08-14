## Why

<!-- One or two sentences. Not a file list. -->

## How to check

- [ ] `python -m pytest` is green locally
- [ ] No customer data, `.env`, CSV, or XLSX in the diff
- [ ] Secrets stay in env examples only (`CHANGE_ME`, never real keys)

## Target

- Feature / fix PRs merge into **`staging`** (test).
- Only a **`staging` → `main`** PR goes to production.

## After merge to staging

Test on the staging stack before opening the production PR.
