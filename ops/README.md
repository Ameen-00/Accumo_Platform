# ops — staging deploys you can undo

Arjun is testing on staging. Treat it as production: back up before you touch
it, verify after, and know how to get back.

## The three commands

```powershell
# 1. Back up. READ-ONLY, safe to run while he is mid-session.
powershell -ExecutionPolicy Bypass -File ops\backup-staging.ps1

# 2. Deploy. Runs tests, builds web, backs up, snapshots, deploys, verifies.
powershell -ExecutionPolicy Bypass -File ops\deploy-staging.ps1

# 3. Undo.
powershell -ExecutionPolicy Bypass -File ops\rollback-staging.ps1
```

## What deploy refuses to do

It stops before touching the server if:

- the tests fail (override with `-SkipTests`, only when you know why)
- the web build fails
- the backup fails (override with `-SkipBackup`)
- **the tarball contains a `.env`** — the server has its own, and overwriting it
  with a laptop copy would break staging in a way that looks like a code bug

After deploying it polls `/health` and the page for up to a minute. If the app
does not answer, it says so and prints the rollback command rather than leaving
you to find out from Arjun.

## What is safe and what is not

| | Safe during a sitting? |
|---|---|
| `backup-staging.ps1` | **Yes** — read-only |
| `rollback-staging.ps1` | ~30s downtime |
| `deploy-staging.ps1` | ~1-2 min downtime. Do not run while he is on the page. |

**Never run `docker compose down -v`.** The `-v` deletes the named volumes,
which is where every confirmation and dismissal Arjun has made is stored.
Losing those loses his review work. None of these scripts use it.

Rollback restores **code only**. The database is untouched, so dispositions
survive. Restoring data is a separate step from a backup:

```
gunzip -c pulse-db-<stamp>.sql.gz | docker compose -f docker/docker-compose.staging.yml exec -T postgres psql -U pulse pulse
```

## Snapshots

`deploy-staging.ps1` tars the current release to `/opt/pulse-releases/` before
replacing it, keeping the last five. A hand-scp'd deploy leaves no snapshot, so
there is nothing to roll back to — which is the reason these scripts exist.

```powershell
powershell -ExecutionPolicy Bypass -File ops\rollback-staging.ps1 -List
```

## Writing more scripts here

**ASCII only.** PowerShell 5.1 reads a `.ps1` without a byte-order mark as ANSI,
so an em-dash becomes three characters, one of which is a smart quote that
PowerShell treats as a string delimiter. The file then fails to parse with an
error pointing at the wrong line. Use `--` and `'`, never `—` or `'`.
