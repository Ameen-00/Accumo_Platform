# Put the previous release back.
#
# Code only. The database and uploaded files are untouched, so anything Arjun
# confirmed or dismissed survives a rollback. If you need to restore data too,
# that is a separate restore from ops\backup-staging.ps1 output.
#
#   powershell -ExecutionPolicy Bypass -File ops\rollback-staging.ps1
#   powershell -ExecutionPolicy Bypass -File ops\rollback-staging.ps1 -List
#   powershell -ExecutionPolicy Bypass -File ops\rollback-staging.ps1 -Release 2026-08-16-104512-previous.tgz

param(
  [switch]$List,
  [string]$Release
)

. "$PSScriptRoot\_common.ps1"
Assert-RepoRoot

$pem = Get-Pem

if ($List) {
  Write-Host "Snapshots on the server (newest first):" -ForegroundColor Cyan
  Invoke-Remote $pem "ls -1t $ReleaseDir/*.tgz 2>/dev/null | xargs -r -n1 basename || echo '  none yet'"
  exit 0
}

if (-not $Release) {
  $Release = (ssh -i $pem -o StrictHostKeyChecking=no $StagingHost "ls -1t $ReleaseDir/*.tgz 2>/dev/null | head -1 | xargs -r basename").Trim()
  if (-not $Release) {
    Write-Host "No snapshots on the server. Nothing to roll back to." -ForegroundColor Red
    Write-Host "Snapshots are created by ops\deploy-staging.ps1 -- a hand-scp'd deploy leaves none." -ForegroundColor DarkGray
    exit 1
  }
}

Write-Host "Rolling back to: $Release" -ForegroundColor Yellow
$confirm = Read-Host "Type YES to continue"
if ($confirm -ne "YES") { Write-Host "Cancelled."; exit 0 }

# Note: no `down -v` anywhere. Volumes stay, so the review work stays.
$remote = @"
set -e
cd $AppDir
tar -xzf $ReleaseDir/$Release
$Compose up -d --build
"@
Invoke-Remote $pem $remote

Write-Host "`nChecking..." -ForegroundColor Cyan
if (Test-Staging) {
  Write-Host "`nRolled back. $StagingUrl is up on $Release." -ForegroundColor Green
} else {
  Write-Host "`nStill not answering after rollback. Look at the logs:" -ForegroundColor Red
  Write-Host "  ssh -i `$env:TEMP\pulse-staging.pem $StagingHost `"cd $AppDir; $Compose logs --tail 80 api`"" -ForegroundColor Yellow
  exit 1
}
