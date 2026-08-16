# Deploy to staging, reversibly.
#
# What makes this different from scp-ing a tarball by hand:
#   - refuses to deploy if the tests fail
#   - refuses to ship a tarball containing .env
#   - snapshots the current release on the server BEFORE replacing it
#   - verifies the app actually answers afterwards
#   - tells you the exact rollback command if it does not
#
# It never runs `down -v`. That flag deletes the named volumes, which is where
# Arjun's confirmations live.
#
#   powershell -ExecutionPolicy Bypass -File ops\deploy-staging.ps1
#   powershell -ExecutionPolicy Bypass -File ops\deploy-staging.ps1 -SkipTests

param(
  [switch]$SkipTests,
  [switch]$SkipBackup
)

. "$PSScriptRoot\_common.ps1"
Assert-RepoRoot

$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
Write-Host "Deploying to $StagingUrl  (release $stamp)" -ForegroundColor Cyan

# --- 1. tests ---------------------------------------------------------------
if (-not $SkipTests) {
  Write-Host "`n[1/7] running tests..." -ForegroundColor Cyan
  python -m pytest -q
  if ($LASTEXITCODE -ne 0) {
    Write-Host "`nTests failed. Not deploying." -ForegroundColor Red
    Write-Host "Use -SkipTests only if you know exactly why they fail." -ForegroundColor DarkGray
    exit 1
  }
} else {
  Write-Host "`n[1/7] tests SKIPPED" -ForegroundColor Yellow
}

# --- 2. build the web bundle ------------------------------------------------
Write-Host "`n[2/7] building web..." -ForegroundColor Cyan
Push-Location web
npm run build
$buildFailed = ($LASTEXITCODE -ne 0)
Pop-Location
if ($buildFailed) {
  Write-Host "`nWeb build failed. Not deploying." -ForegroundColor Red
  exit 1
}

# --- 3. backup before touching anything -------------------------------------
if (-not $SkipBackup) {
  Write-Host "`n[3/7] backing up first..." -ForegroundColor Cyan
  & "$PSScriptRoot\backup-staging.ps1"
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Backup failed. Not deploying." -ForegroundColor Red
    exit 1
  }
} else {
  Write-Host "`n[3/7] backup SKIPPED" -ForegroundColor Yellow
}

# --- 4. pack ----------------------------------------------------------------
Write-Host "`n[4/7] packing..." -ForegroundColor Cyan
$tar = Join-Path $env:TEMP "pulse-$stamp.tgz"
tar -czf $tar `
  --exclude=".env" --exclude=".env.*" `
  --exclude="__pycache__" --exclude="*.pyc" `
  packages apps web/dist docker requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "tar failed" -ForegroundColor Red; exit 1 }

# The server keeps its own .env. Shipping ours would overwrite the staging
# secrets with whatever is on this laptop -- check rather than trust the flag.
$leaked = (tar -tzf $tar) | Select-String -Pattern "(^|/)\.env"
if ($leaked) {
  Write-Host "`nABORT: the tarball contains an .env file:" -ForegroundColor Red
  $leaked | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
  Remove-Item $tar -Force
  exit 1
}
Write-Host "  $([math]::Round((Get-Item $tar).Length/1MB,1)) MB, no .env" -ForegroundColor Green

# --- 5. ship ----------------------------------------------------------------
Write-Host "`n[5/7] uploading..." -ForegroundColor Cyan
$pem = Get-Pem
scp -i $pem -o StrictHostKeyChecking=no $tar "${StagingHost}:/tmp/pulse-new.tgz"
if ($LASTEXITCODE -ne 0) { Write-Host "upload failed" -ForegroundColor Red; exit 1 }

# --- 6. snapshot the current release, then replace it ------------------------
Write-Host "`n[6/7] snapshotting current release and deploying..." -ForegroundColor Cyan
$remote = @"
set -e
mkdir -p $ReleaseDir
cd $AppDir
tar -czf $ReleaseDir/$stamp-previous.tgz --exclude='.env' packages apps web docker requirements.txt 2>/dev/null || true
ls -1t $ReleaseDir/*.tgz | tail -n +6 | xargs -r rm --
tar -xzf /tmp/pulse-new.tgz
rm -f /tmp/pulse-new.tgz
$Compose up -d --build
"@
Invoke-Remote $pem $remote

# --- 7. prove it works ------------------------------------------------------
Write-Host "`n[7/7] checking the app answers..." -ForegroundColor Cyan
if (Test-Staging) {
  Write-Host "`nDeployed. $StagingUrl is up." -ForegroundColor Green
  Write-Host "Tell Arjun to hard-refresh (Ctrl+Shift+R) before he tries again." -ForegroundColor DarkGray
  Write-Host "`nIf something looks wrong, roll back with:" -ForegroundColor DarkGray
  Write-Host "  powershell -ExecutionPolicy Bypass -File ops\rollback-staging.ps1" -ForegroundColor DarkGray
} else {
  Write-Host "`nDEPLOYED BUT NOT ANSWERING." -ForegroundColor Red
  Write-Host "Roll back now:" -ForegroundColor Red
  Write-Host "  powershell -ExecutionPolicy Bypass -File ops\rollback-staging.ps1" -ForegroundColor Yellow
  Write-Host "`nOr look at what it said:" -ForegroundColor DarkGray
  Write-Host "  ssh -i `$env:TEMP\pulse-staging.pem $StagingHost `"cd $AppDir; $Compose logs --tail 80 api`"" -ForegroundColor DarkGray
  exit 1
}
