<#
.SYNOPSIS
    Start CreditProbe for a client demonstration, and prove it is ready.

.DESCRIPTION
    One command. It brings the stack up, applies migrations, verifies the demo
    workspace, warms the deterministic paths, and only then opens the browser.

    It makes NO live provider call and starts no evaluation. The expensive
    verification modes are yours to run deliberately - see
    docs/CLIENT_DEMO_RUNBOOK.md.

    The order matters. Opening a browser at a half-started stack is how a
    presenter ends up demonstrating a loading spinner.

.PARAMETER Rebuild
    Rebuild the images first. Use after pulling new code.

.PARAMETER Reset
    Rebuild the demonstration workspace to its known state before starting.

.PARAMETER NoBrowser
    Do not open the browser.

.PARAMETER SkipCheck
    Skip the pre-flight. Not recommended: the pre-flight is the only thing
    standing between a missing .env and a client watching you find out.

.EXAMPLE
    .\scripts\demo-start.ps1

.EXAMPLE
    .\scripts\demo-start.ps1 -Rebuild -Reset

.NOTES
    Windows PowerShell 5.1 and PowerShell 7. Docker Desktop only.

    Exit codes
        0   started and ready
        1   something failed; the reason is printed
#>
[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$Reset,
    [switch]$NoBrowser,
    [switch]$SkipCheck
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host ('-> {0}' -f $Text) -ForegroundColor Cyan
}

function Stop-With {
    param([string]$Reason)
    Write-Host ''
    Write-Host ('STOPPED: {0}' -f $Reason) -ForegroundColor Red
    Pop-Location
    exit 1
}

function Wait-For {
    param([string]$Url, [int]$Seconds = 180, [string]$What = 'the service')
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing -Method Get
            if ([int]$response.StatusCode -lt 500) { return $true }
        }
        catch { Start-Sleep -Seconds 3 }
    }
    Write-Host ('  {0} did not become healthy within {1}s' -f $What, $Seconds) -ForegroundColor Red
    return $false
}

Write-Host ''
Write-Host 'CreditProbe - starting the demonstration stack' -ForegroundColor White
Write-Host 'No live provider call is made by this script.' -ForegroundColor DarkGray

# ------------------------------------------------------------------- 1. .env
Write-Step 'Checking configuration'

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.env'))) {
    Stop-With '.env is missing. Copy .env.example, fill it in, and run this again.'
}
Write-Host '  .env is present. Its contents are never read or printed by this script.'

$compose = & docker compose config -q 2>&1
if ($LASTEXITCODE -ne 0) {
    Stop-With ('docker-compose.yml is not valid: {0}' -f ($compose -join ' '))
}
Write-Host '  docker-compose.yml is valid.'

# --------------------------------------------------------------- 2. the stack
Write-Step 'Starting the stack'

if ($Rebuild) {
    Write-Host '  building images (this takes a few minutes) ...'
    & docker compose build
    if ($LASTEXITCODE -ne 0) { Stop-With 'the image build failed.' }
}

& docker compose up -d
if ($LASTEXITCODE -ne 0) { Stop-With 'docker compose up failed.' }

Write-Step 'Waiting for health'
if (-not (Wait-For -Url 'http://localhost:8000/api/v1/health' -What 'the backend')) {
    Write-Host '  docker compose logs --tail=80 backend' -ForegroundColor Gray
    Stop-With 'the backend never became healthy.'
}
Write-Host '  backend is healthy.'

if (-not (Wait-For -Url 'http://localhost:3000' -Seconds 240 -What 'the front end')) {
    Stop-With 'the front end never became reachable.'
}
Write-Host '  front end is reachable.'

if (-not (Wait-For -Url 'http://localhost:3000/api/v1/health' -Seconds 60 -What 'the API proxy')) {
    Stop-With 'the browser cannot reach the API through the front end.'
}
Write-Host '  the browser can reach the API.'

# --------------------------------------------------------------- 3. migrations
Write-Step 'Applying migrations'

& docker compose exec -T backend alembic upgrade head
if ($LASTEXITCODE -ne 0) { Stop-With 'migrations failed.' }
$head = (& docker compose exec -T backend alembic current 2>&1 | Select-Object -Last 1)
Write-Host ('  migration head: {0}' -f ($head -replace '\s+', ' ').Trim())

# ------------------------------------------------------------ 4. demo workspace
Write-Step 'Demonstration workspace'

if ($Reset) {
    Write-Host '  rebuilding the demo workspace to its known state ...'
    & docker compose exec -T backend python scripts/demo_state.py --rebuild --yes
    if ($LASTEXITCODE -ne 0) { Stop-With 'the demo workspace could not be rebuilt.' }
}
else {
    & docker compose exec -T backend python scripts/demo_state.py --check
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  The workspace is not clean. Run this again with -Reset.' -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------------- 5. prewarm
# Section 26: connections, caches, the registry and the compiled queries - never an
# answer. Nothing here calls the model, and nothing changes what a user sees.
Write-Step 'Warming the deterministic paths (no model call)'

foreach ($endpoint in @(
        '/api/v1/health',
        '/api/v1/catalog',
        '/api/v1/data-builder/datasets',
        '/api/v1/data-builder/domains',
        '/api/v1/studio',
        '/api/v1/engine/analyses',
        '/api/v1/engine/periods',
        '/api/v1/risk-cases',
        '/api/v1/projects',
        '/api/v1/investigations')) {
    try {
        $null = Invoke-WebRequest -Uri ('http://localhost:8000{0}' -f $endpoint) `
            -TimeoutSec 60 -UseBasicParsing -Method Get
        Write-Host ('  warmed {0}' -f $endpoint) -ForegroundColor DarkGray
    }
    catch {
        Write-Host ('  {0} did not answer - the demo may be slow on first use' -f $endpoint) -ForegroundColor Yellow
    }
}

foreach ($route in @('/', '/projects', '/investigations', '/analyses', '/studio',
        '/data-builder', '/trace', '/workflow')) {
    try {
        $null = Invoke-WebRequest -Uri ('http://localhost:3000{0}' -f $route) `
            -TimeoutSec 60 -UseBasicParsing -Method Get
    }
    catch { }
}
Write-Host '  browser routes warmed.'

# ------------------------------------------------------------------ 6. verdict
if (-not $SkipCheck) {
    Write-Step 'Pre-flight'
    & (Join-Path $PSScriptRoot 'demo-check.ps1')
    $checkCode = $LASTEXITCODE
}
else {
    $checkCode = 0
    Write-Host ''
    Write-Host 'Pre-flight SKIPPED at your request.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '== Sign in ==============================================' -ForegroundColor Cyan
Write-Host '  Administrator   alex.rahman    creditprobe-demo'
Write-Host '  Data Steward    sara.qahtani   creditprobe-demo'
Write-Host '  Analyst         omar.nasser    creditprobe-demo'
Write-Host '  Viewer          layla.haddad   creditprobe-demo'
Write-Host '  Demonstration passwords on synthetic data. Not secrets, and' -ForegroundColor DarkGray
Write-Host '  not to be reused anywhere.' -ForegroundColor DarkGray

$demo = $null
try { $demo = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/demo' -TimeoutSec 10 } catch { }
Write-Host ''
if ($null -ne $demo -and $demo.demo_mode) {
    Write-Host ('  Demo Mode       ON  ({0})' -f $demo.data_release) -ForegroundColor Green
}
else {
    Write-Host '  Demo Mode       OFF - the synthetic-data label will not appear' -ForegroundColor Yellow
}
if ($null -ne $demo -and $demo.demo_safe_mode) {
    Write-Host '  Demo Safe Mode  ON' -ForegroundColor Green
}
else {
    Write-Host '  Demo Safe Mode  OFF' -ForegroundColor Yellow
}

$badge = $null
try { $badge = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/validation/ai-badge' -TimeoutSec 10 } catch { }
if ($null -ne $badge -and $badge.live_verified) {
    Write-Host ('  Live verified   YES for {0}' -f $badge.verified_short_sha) -ForegroundColor Green
}
elseif ($null -ne $badge -and $badge.stale) {
    Write-Host ('  Live verified   STALE - {0}' -f $badge.reason) -ForegroundColor Yellow
}
else {
    Write-Host '  Live verified   NO - this build has not been live verified' -ForegroundColor Yellow
    Write-Host '                  Run .\scripts\verify-live-ai.ps1 -Quick to verify.' -ForegroundColor DarkGray
}

if (-not $NoBrowser -and $checkCode -eq 0) {
    Start-Process 'http://localhost:3000'
}
elseif ($checkCode -ne 0) {
    Write-Host ''
    Write-Host 'The browser was NOT opened: the pre-flight said NO-GO.' -ForegroundColor Red
}

Pop-Location
exit $checkCode
