# Start CreditProbe for local development - one command, on Windows.
#
#     .\scripts\dev.ps1
#
# If Windows refuses to run it, allow local scripts once with:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
# It starts everything CreditProbe needs, in order, waiting for each part to be ready:
#
#   1. PostgreSQL           (in Docker, so you do not have to install it)
#   2. Database migrations  (creates or updates the tables)
#   3. The analytical lake  (converts the source workbook to Parquet, if needed)
#   4. The backend API      (FastAPI, on port 8000)
#   5. The frontend         (Next.js, on port 3000)
#
# Press Ctrl+C once to stop the backend and frontend. PostgreSQL keeps running;
# stop it with `docker compose down`.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path

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

Step "Checking prerequisites"

if (-not (Test-Path ".env")) {
    Die "No .env file found." "Run:  copy .env.example .env    then open .env and set POSTGRES_PASSWORD."
}

# Load .env into this process so the backend, Docker Compose and Next.js agree.
Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $name, $value = $line.Split("=", 2)
        # Strip an inline comment, then surrounding quotes.
        $value = ($value -replace '\s+#.*$', '').Trim().Trim('"').Trim("'")
        [Environment]::SetEnvironmentVariable($name.Trim(), $value, "Process")
    }
}
Ok ".env loaded"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die "Docker is not installed." "Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Die "Docker is installed but not running." "Start Docker Desktop, wait for it to say 'Running', then try again."
}
Ok "Docker is running"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Die "Node.js is not installed." "Install Node.js 20 or newer from https://nodejs.org/"
}
Ok "Node.js $(node -v)"

if (Test-Path ".venv\Scripts\python.exe") {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
} elseif (Test-Path ".venv/bin/python") {
    $Python = Join-Path $Root ".venv/bin/python"
} else {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $Python) { Die "Python is not installed." "Install Python 3.11 or newer from https://www.python.org/downloads/" }
    Warn "No .venv found - using $Python. Create one with:  python -m venv .venv"
}
Ok "Python found"

& $Python -c "import fastapi, duckdb, sqlalchemy" *> $null
if ($LASTEXITCODE -ne 0) {
    Die "The Python packages are not installed." "Run:  $Python -m pip install -r requirements.txt"
}
Ok "Python packages installed"

if (-not (Test-Path "frontend\node_modules")) {
    Die "The frontend packages are not installed." "Run:  cd frontend  then  npm install"
}
Ok "Frontend packages installed"

# ---------------------------------------------------------------- database

Step "Starting PostgreSQL"
docker compose up -d db | Out-Null

$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "ipm_app" }
$pgDb   = if ($env:POSTGRES_DB)   { $env:POSTGRES_DB }   else { "ipm" }

Write-Host "  waiting for the database" -NoNewline
$ready = $false
foreach ($i in 1..60) {
    docker compose exec -T db pg_isready -U $pgUser -d $pgDb *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 1
}
Write-Host ""
if (-not $ready) { Die "PostgreSQL did not become ready in 60 seconds." "Check it with:  docker compose logs db" }
Ok "PostgreSQL is ready"

# -------------------------------------------------------------- migrations

Step "Applying database migrations"
& $Python -m alembic upgrade head
Ok "Database schema is up to date"

# --------------------------------------------------------------- data lake

Step "Checking the analytical data"
$analyticsDir = if ($env:DATA_ANALYTICS_DIR) { $env:DATA_ANALYTICS_DIR } else { "data/analytics" }
if (Test-Path (Join-Path $analyticsDir "portfolio_facility")) {
    Ok "Analytical layer already built"
} else {
    Warn "Not built yet - building it now (this takes a few seconds)"
    & $Python scripts/generate_saudi_universe.py
}

# ----------------------------------------------------------------- backend

Step "Starting the backend API"
$apiHost = if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }
$apiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$api = Start-Process -FilePath $Python `
    -ArgumentList "-m", "uvicorn", "backend.api.main:app", "--host", $apiHost, "--port", $apiPort, "--reload" `
    -RedirectStandardOutput "logs\api-dev.log" -RedirectStandardError "logs\api-dev.err.log" `
    -NoNewWindow -PassThru

Write-Host "  waiting for the API" -NoNewline
$apiReady = $false
foreach ($i in 1..40) {
    try {
        Invoke-WebRequest -Uri "http://${apiHost}:${apiPort}/healthz" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $apiReady = $true; break
    } catch { Write-Host "." -NoNewline; Start-Sleep -Seconds 1 }
}
Write-Host ""
if (-not $apiReady) { Die "The API did not start." "Look at what went wrong in:  logs\api-dev.log" }
Ok "API ready at http://${apiHost}:${apiPort}"

# ---------------------------------------------------------------- frontend

Step "Starting the frontend"
$web = Start-Process -FilePath "npm" -ArgumentList "run", "dev" `
    -WorkingDirectory (Join-Path $Root "frontend") `
    -RedirectStandardOutput "$Root\logs\web-dev.log" -RedirectStandardError "$Root\logs\web-dev.err.log" `
    -NoNewWindow -PassThru

Write-Host "  waiting for the frontend" -NoNewline
foreach ($i in 1..90) {
    try {
        Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 2 | Out-Null
        break
    } catch { Write-Host "." -NoNewline; Start-Sleep -Seconds 1 }
}
Write-Host ""
Ok "Frontend ready"

Write-Host ""
Write-Host "  CreditProbe is running." -ForegroundColor Green
Write-Host ""
Write-Host "    Open this in your browser:   http://localhost:3000"
Write-Host ""
Write-Host "    API                          http://${apiHost}:${apiPort}"
Write-Host "    API documentation            http://${apiHost}:${apiPort}/docs"
Write-Host "    Health check                 http://${apiHost}:${apiPort}/api/v1/health"
Write-Host ""
Write-Host "    Logs:  logs\api-dev.log   logs\web-dev.log"
Write-Host "    Press Ctrl+C to stop."
Write-Host ""

try {
    Wait-Process -Id $api.Id
} finally {
    Write-Host ""
    Step "Shutting down"
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue
    Ok "Backend and frontend stopped"
    Write-Host "  PostgreSQL is still running. Stop it with: docker compose down"
}
