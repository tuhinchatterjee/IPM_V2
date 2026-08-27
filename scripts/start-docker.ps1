# Start CreditProbe on Windows using Docker - one command.
#
#     .\scripts\start-docker.ps1
#
# If Windows refuses to run it, allow local scripts once with:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
# Nothing has to be installed on this machine except Docker Desktop. Node.js,
# Python and PostgreSQL all run inside the containers.
#
# Options:
#     .\scripts\start-docker.ps1 -Rebuild    force a full rebuild of the images
#     .\scripts\start-docker.ps1 -Logs       follow the logs after starting

param(
    [switch]$Rebuild,
    [switch]$Logs
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Step($m) { Write-Host ""; Write-Host "> $m" -ForegroundColor White }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die($m, $fix) {
    Write-Host ""
    Write-Host "  [x] $m" -ForegroundColor Red
    if ($fix) { Write-Host ""; Write-Host "  How to fix it:"; Write-Host "  $fix" }
    Write-Host ""
    exit 1
}

# ------------------------------------------------------------------ checks

Step "Checking Docker Desktop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die "Docker is not installed." `
        "Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Die "Docker Desktop is installed but not running." `
        "Open Docker Desktop, wait until it says 'Running', then run this again."
}
Ok "Docker Desktop is running"

# .env is optional: docker-compose.yml carries development defaults for
# everything CreditProbe needs. It is only mentioned so the choice is visible.
if (Test-Path ".env") { Ok "Using the settings in your .env file" }
else { Warn "No .env file - using the built-in development defaults (this is fine)" }

# --------------------------------------------------------------- start it

Step "Building and starting CreditProbe"
Write-Host "  The first run downloads and builds the containers." -ForegroundColor DarkGray
Write-Host "  Expect 5-10 minutes the first time, and a few seconds after that." -ForegroundColor DarkGray
Write-Host ""

if ($Rebuild) { docker compose build --no-cache }
docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    Die "CreditProbe did not start." "See what went wrong with:  docker compose logs"
}

# -------------------------------------------------------------- wait for it

Step "Waiting for CreditProbe to be ready"
$ready = $false
foreach ($attempt in 1..120) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:3000/api/v1/health" `
                               -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}

if (-not $ready) {
    Die "CreditProbe started but is not answering yet." `
        "Give it another minute, then check:  docker compose logs backend"
}

Write-Host ""
Write-Host "  CreditProbe is running." -ForegroundColor Green
Write-Host ""
Write-Host "    Open this in your browser:   http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "    API                          http://localhost:8000"
Write-Host "    API documentation            http://localhost:8000/docs"
Write-Host "    Health check                 http://localhost:8000/api/v1/health"
Write-Host ""
Write-Host "    Logs:   docker compose logs -f" -ForegroundColor DarkGray
Write-Host "    Stop:   .\scripts\stop-docker.ps1" -ForegroundColor DarkGray
Write-Host ""

if ($Logs) { docker compose logs -f }
