# Shared helpers for the staging ops scripts.
# Dot-source this: . "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"

$StagingHost = "ubuntu@13.127.41.18"
$StagingUrl  = "https://staging.pulse.accumo.co"
$AppDir      = "/opt/pulse"
# /opt is root-owned, so the ubuntu user cannot create a sibling of /opt/pulse
# there. Keeping snapshots under the home directory avoids needing sudo, and
# keeps them outside the app dir so extracting a release cannot clobber them.
$ReleaseDir  = "/home/ubuntu/pulse-releases"
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

  # A previous run (or the manual icacls in the handover) leaves this file with
  # inheritance stripped and read-only. Copy-Item -Force then cannot overwrite
  # it and the whole deploy dies here. Take ownership back before replacing.
  if (Test-Path $dest) {
    icacls $dest /grant:r "$($env:USERNAME):(F)" 2>&1 | Out-Null
    Remove-Item $dest -Force -ErrorAction SilentlyContinue
  }

  Copy-Item $PemSource $dest -Force

  # ssh refuses a key that other accounts can read. Removing inheritance drops
  # every inherited ACE; the grant then makes this user the only one on it.
  # Full rather than read, so the next run can overwrite it.
  icacls $dest /inheritance:r 2>&1 | Out-Null
  icacls $dest /grant:r "$($env:USERNAME):(F)" 2>&1 | Out-Null
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
