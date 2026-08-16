# Shared helpers for the staging ops scripts.
# Dot-source this: . "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"

$StagingHost = "ubuntu@13.127.41.18"
$StagingUrl  = "https://staging.pulse.accumo.co"
$AppDir      = "/opt/pulse"
$ReleaseDir  = "/opt/pulse-releases"
$Compose     = "docker compose -f docker/docker-compose.staging.yml"
$PemSource   = "$env:USERPROFILE\Documents\pulse-staging.pem"

# Windows refuses to use a key whose ACL is inherited from Documents -- ssh
# reports "bad permissions" and gives up. Copy to TEMP and strip inheritance.
# The copy is overwritten each run and never leaves the machine.
function Get-Pem {
  $dest = Join-Path $env:TEMP "pulse-staging.pem"
  if (-not (Test-Path $PemSource)) {
    throw "SSH key not found at $PemSource"
  }
  Copy-Item $PemSource $dest -Force
  icacls $dest /inheritance:r | Out-Null
  icacls $dest /grant:r "$($env:USERNAME):(R)" | Out-Null
  return $dest
}

function Invoke-Remote {
  param([string]$Pem, [string]$Command)
  ssh -i $Pem -o StrictHostKeyChecking=no $StagingHost $Command
  if ($LASTEXITCODE -ne 0) { throw "Remote command failed: $Command" }
}

# Returns $true only if the app answers correctly. Used after every deploy and
# rollback -- a container that started is not the same as an app that works.
function Test-Staging {
  param([int]$Retries = 12, [int]$DelaySeconds = 5)

  for ($i = 1; $i -le $Retries; $i++) {
    try {
      $health = Invoke-RestMethod -Uri "$StagingUrl/health" -TimeoutSec 10
      $page   = Invoke-WebRequest -Uri $StagingUrl -TimeoutSec 10 -UseBasicParsing
      if ($page.StatusCode -eq 200) {
        Write-Host "  health OK after $($i * $DelaySeconds)s" -ForegroundColor Green
        return $true
      }
    } catch {
      Write-Host "  waiting for the app... ($i/$Retries)" -ForegroundColor DarkGray
    }
    Start-Sleep -Seconds $DelaySeconds
  }
  return $false
}

function Assert-RepoRoot {
  if (-not (Test-Path "docker/docker-compose.staging.yml")) {
    throw "Run this from the accumo-platform root, not from ops/."
  }
}
