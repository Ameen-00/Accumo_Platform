# Back up the staging database and uploaded files to this laptop.
#
# READ-ONLY on the server. Safe to run while Arjun is mid-session -- it does not
# stop a container, touch a volume, or write anything the app reads.
#
# Run it before every deploy, and once at the end of a sitting. Arjun's
# confirmations and dismissals live in that database and exist nowhere else;
# losing them loses his review work and his trust in one stroke.
#
#   powershell -ExecutionPolicy Bypass -File ops\backup-staging.ps1

. "$PSScriptRoot\_common.ps1"
Assert-RepoRoot

$stamp   = Get-Date -Format "yyyy-MM-dd-HHmmss"
$outDir  = "$env:USERPROFILE\Documents\pulse-backups\$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Write-Host "Backing up staging -> $outDir" -ForegroundColor Cyan
$pem = Get-Pem

Write-Host "`n[1/3] dumping postgres..." -ForegroundColor Cyan
Invoke-Remote $pem "cd $AppDir; $Compose exec -T postgres pg_dump -U pulse pulse | gzip > /tmp/pulse-db-$stamp.sql.gz"

Write-Host "[2/3] packing uploaded files..." -ForegroundColor Cyan
# Read from the running container's mount rather than the raw volume path, so
# this works regardless of where Docker put it.
Invoke-Remote $pem "cd $AppDir; $Compose exec -T api tar -czf - -C /data . > /tmp/pulse-files-$stamp.tgz"

Write-Host "[3/3] pulling to this machine..." -ForegroundColor Cyan
scp -i $pem -o StrictHostKeyChecking=no "${StagingHost}:/tmp/pulse-db-$stamp.sql.gz"   "$outDir\"
scp -i $pem -o StrictHostKeyChecking=no "${StagingHost}:/tmp/pulse-files-$stamp.tgz"   "$outDir\"
Invoke-Remote $pem "rm -f /tmp/pulse-db-$stamp.sql.gz /tmp/pulse-files-$stamp.tgz"

$db = Get-Item "$outDir\pulse-db-$stamp.sql.gz"
if ($db.Length -lt 1024) {
  Write-Host "`nWARNING: the dump is $($db.Length) bytes. That is too small to be real." -ForegroundColor Red
  Write-Host "Check the database is up before trusting this backup." -ForegroundColor Red
  exit 1
}

Write-Host "`nDone." -ForegroundColor Green
Get-ChildItem $outDir | Format-Table Name, @{n="Size";e={"{0:N0} KB" -f ($_.Length/1KB)}}

Write-Host "To restore this dump later:" -ForegroundColor DarkGray
Write-Host "  gunzip -c pulse-db-$stamp.sql.gz | docker compose -f docker/docker-compose.staging.yml exec -T postgres psql -U pulse pulse" -ForegroundColor DarkGray
