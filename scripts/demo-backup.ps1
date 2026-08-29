<#
.SYNOPSIS
    Back up everything the demonstration needs to be put back.

.DESCRIPTION
    Run this the evening before. It captures a database dump and a manifest of
    exactly what was running, so a demonstration that goes wrong can be
    restored rather than rebuilt from memory.

    WHAT IT CAPTURES
        A pg_dump of the platform database.
        The commit, the branch and whether the tree was clean.
        The migration head.
        The running image ids and tags.
        The demonstration posture and data release.
        The active Teaching, Regulatory and Learning Releases.
        Whether .env exists - never its contents.
        The current live-verification report, if there is one.

    WHAT IT NEVER CAPTURES
        The API key. The .env file itself. Any value from it.

    A backup that contains a credential is a credential you now have to
    protect in one more place, and the one place nobody remembers to.

.PARAMETER Path
    Where to write. Default: backups\demo-<timestamp>\ under the repository.

.EXAMPLE
    .\scripts\demo-backup.ps1

.NOTES
    Windows PowerShell 5.1 and PowerShell 7. Docker Desktop only.

    Restoring is described in the manifest itself, and in
    docs/CLIENT_DEMO_RUNBOOK.md.
#>
[CmdletBinding()]
param(
    [string]$Path = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

$stamp = (Get-Date).ToString('yyyy-MM-dd-HHmm')
if (-not $Path) {
    $Path = Join-Path (Join-Path $RepoRoot 'backups') ('demo-{0}' -f $stamp)
}
$null = New-Item -ItemType Directory -Path $Path -Force

Write-Host ''
Write-Host 'CreditProbe - demonstration backup' -ForegroundColor White
Write-Host ('  writing to {0}' -f $Path)

function Get-JsonOrNull {
    param([string]$Url)
    try { return Invoke-RestMethod -Uri $Url -TimeoutSec 15 -Method Get }
    catch { return $null }
}

# ------------------------------------------------------------- the database
Write-Host ''
Write-Host '-> Database' -ForegroundColor Cyan

$dumpPath = Join-Path $Path 'creditprobe.sql'
$dumped = $false
try {
    # -T keeps stdin closed so this works from a script and from CI.
    & docker compose exec -T db pg_dump -U ipm_app -d ipm |
        Out-File -LiteralPath $dumpPath -Encoding utf8
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $dumpPath)) {
        $sizeMb = [math]::Round((Get-Item -LiteralPath $dumpPath).Length / 1MB, 1)
        Write-Host ('  dumped {0} MB' -f $sizeMb) -ForegroundColor Green
        $dumped = $true
    }
}
catch {
    Write-Host ('  the dump failed: {0}' -f $_.Exception.Message) -ForegroundColor Red
}
if (-not $dumped) {
    Write-Host '  NO DATABASE DUMP WAS TAKEN. This backup cannot restore data.' -ForegroundColor Red
}

# -------------------------------------------------------------- the manifest
Write-Host ''
Write-Host '-> Manifest' -ForegroundColor Cyan

$branch = (& git rev-parse --abbrev-ref HEAD 2>&1).Trim()
$sha = (& git rev-parse HEAD 2>&1).Trim()
$dirty = ((& git status --porcelain 2>&1) -join '').Trim()

$head = ''
try {
    $head = ((& docker compose exec -T backend alembic current 2>&1) |
        Select-Object -Last 1) -replace '\s+', ' '
}
catch { $head = 'unknown' }

$images = @()
try {
    $images = @(& docker compose images --format '{{.Service}} {{.Repository}}:{{.Tag}} {{.ID}}' 2>&1)
}
catch { }

$demo = Get-JsonOrNull 'http://localhost:8000/api/v1/demo'
$badge = Get-JsonOrNull 'http://localhost:8000/api/v1/validation/ai-badge'
$build = Get-JsonOrNull 'http://localhost:8000/api/v1/build'
$releases = Get-JsonOrNull 'http://localhost:8000/api/v1/learning/releases'
$regulatory = Get-JsonOrNull 'http://localhost:8000/api/v1/regulatory/releases'

$manifest = [pscustomobject]@{
    taken_at            = (Get-Date).ToString('o')
    branch              = $branch
    commit              = $sha
    working_tree        = $(if ($dirty) { 'dirty' } else { 'clean' })
    migration_head      = $head.Trim()
    images              = $images
    database_dump       = $(if ($dumped) { 'creditprobe.sql' } else { '' })
    demo_mode           = $demo
    live_verification   = $badge
    build               = $build
    learning_releases   = $releases
    regulatory_releases = $regulatory
    # PRESENCE only. Never the contents, never a value, never a key.
    env_file_present    = (Test-Path -LiteralPath (Join-Path $RepoRoot '.env'))
    restore             = @(
        'docker compose up -d db',
        'docker compose exec -T db psql -U ipm_app -d postgres -c "DROP DATABASE IF EXISTS ipm;"',
        'docker compose exec -T db psql -U ipm_app -d postgres -c "CREATE DATABASE ipm OWNER ipm_app;"',
        'Get-Content .\creditprobe.sql | docker compose exec -T db psql -U ipm_app -d ipm',
        'docker compose exec -T backend alembic current   # confirm the head matches',
        '.\scripts\demo-check.ps1'
    )
}

$manifestPath = Join-Path $Path 'manifest.json'
$manifest | ConvertTo-Json -Depth 8 | Out-File -LiteralPath $manifestPath -Encoding utf8
Write-Host ('  wrote {0}' -f $manifestPath) -ForegroundColor Green

# ------------------------------------------------------- the stored reports
$logDirectory = Join-Path $RepoRoot 'logs'
if (Test-Path -LiteralPath $logDirectory) {
    $reports = @(Get-ChildItem -LiteralPath $logDirectory -Filter '*verification*.json' -ErrorAction SilentlyContinue)
    if ($reports.Count -gt 0) {
        $target = Join-Path $Path 'reports'
        $null = New-Item -ItemType Directory -Path $target -Force
        foreach ($report in $reports) {
            Copy-Item -LiteralPath $report.FullName -Destination $target -Force
        }
        Write-Host ('  copied {0} verification report(s)' -f $reports.Count) -ForegroundColor Green
    }
}

Write-Host ''
if ($dumped) {
    Write-Host 'Backup complete.' -ForegroundColor Green
}
else {
    Write-Host 'Backup INCOMPLETE - the manifest was written but the data was not.' -ForegroundColor Red
}
Write-Host '  No API key, no .env and no credential is in this folder.' -ForegroundColor DarkGray
Write-Host ('  Restore steps are in {0}' -f $manifestPath) -ForegroundColor Gray

Pop-Location
if ($dumped) { exit 0 } else { exit 1 }
