<#
Start the CreditProbe Tool in Docker, against the PostgreSQL running on this PC.

Usage (from the project root):
    powershell -ExecutionPolicy Bypass -File scripts\app-start.ps1

Then open http://localhost:8050

Reads DATABASE_URL / SECRET_KEY / ANTHROPIC_API_KEY from .env and passes them to
the container as environment variables, so nothing secret is stored in the image.

The database host is rewritten from localhost to host.docker.internal, because
inside a container "localhost" means the container itself, not this PC. That is
the single most common reason the container fails to start.

Stop it again with scripts\app-stop.ps1.

NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI unless
the file has a BOM, so characters like a long dash break the parser.
#>

[CmdletBinding()]
param(
    # Host port to publish. The app inside the container always listens on 8050.
    [int]$Port = 8050,
    [string]$ContainerName = "CreditProbe",
    [string]$Image = "ipm-tool:0.1.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"

if (-not (Test-Path $envFile)) {
    throw ".env not found at $envFile. Copy .env.example to .env and fill it in."
}

# Read one KEY=value out of .env. Values are never echoed to the console.
function Get-EnvValue([string]$name) {
    $line = Select-String -Path $envFile -Pattern "^\s*$name\s*=" | Select-Object -First 1
    if (-not $line) { return "" }
    return ($line.Line -split '=', 2)[1].Trim()
}

$dbUrl = Get-EnvValue "DATABASE_URL"
if (-not $dbUrl) {
    throw "DATABASE_URL is missing from .env. The app cannot start without it (backend/db/engine.py)."
}
# localhost inside a container is the container, so point it back at this PC.
$dbUrl = $dbUrl -replace 'localhost', 'host.docker.internal' -replace '127\.0\.0\.1', 'host.docker.internal'

$secret = Get-EnvValue "SECRET_KEY"
if (-not $secret) {
    Write-Warning "SECRET_KEY is not set in .env. Everyone will be logged out every time the container restarts."
}
$apiKey = Get-EnvValue "ANTHROPIC_API_KEY"

# Replace any previous instance so this script is safe to re-run. Checked first
# rather than relying on `docker rm -f`: removing a container that does not exist
# writes to stderr, which $ErrorActionPreference = "Stop" turns into a fatal error.
$existing = docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}"
if ($existing) {
    docker rm -f $ContainerName | Out-Null
}

Write-Host "Starting $ContainerName on port $Port ..."
docker run -d --init `
    --name $ContainerName `
    --restart unless-stopped `
    --add-host=host.docker.internal:host-gateway `
    -p "${Port}:8050" `
    -e DATABASE_URL=$dbUrl `
    -e SECRET_KEY=$secret `
    -e ANTHROPIC_API_KEY=$apiKey `
    -v ipm-logs:/app/logs `
    -v ipm-uploads:/app/uploads `
    $Image | Out-Null

# The app loads the dataset before it answers, so a cold start takes about 30s.
Write-Host "Waiting for the app to come up (this takes about 30 seconds) ..."
$deadline = (Get-Date).AddSeconds(180)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) {
            Write-Host ""
            Write-Host "  CreditProbe Tool is running:  http://localhost:$Port" -ForegroundColor Green
            Write-Host ""
            Write-Host "  Logs:  docker logs -f $ContainerName"
            Write-Host "  Stop:  powershell -File scripts\app-stop.ps1"
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 5
}

Write-Warning "The app did not respond in time. Recent container output:"
docker logs $ContainerName --tail 30
exit 1
