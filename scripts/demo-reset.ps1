<#
.SYNOPSIS
    Rebuild the demonstration workspace to its known state.

.DESCRIPTION
    Between rehearsals, and between one client and the next, the demonstration
    should start from the same place. This removes what people did and puts
    back what the demonstration is about.

    REMOVED
        Projects, Investigations and their messages, saved Analyses, workflow
        items and their history, notifications, comments, Risk Cases, agent
        runs and tasks, Lenses, analysis runs, Assurance records,
        feedback and learning observations, and per-user grid preferences.

    NEVER TOUCHED
        The governed datasets, domains, fields and relationships. The teaching
        library. Regulatory, Teaching and Learning Releases and their
        approvals. User credentials. Alembic's version table. Your .env.

    Then it seeds the demonstration workspace again: one Project, a global
    Investigation and a Project-only one, three saved Analyses executed by the
    deterministic engine, the Risk Cases the real new-period review finds, one
    workflow item and one Lens.

    Nothing here is fabricated. The analyses are run; the Risk Cases come from
    the actual deterministic screen over the data.

.PARAMETER Preview
    Show what would be removed and change nothing. Also available as -WhatIf.

.PARAMETER IncludeUsers
    Also remove the ten accounts the test suite creates (wf_author,
    gridpref.one and the rest). The four demonstration accounts are kept.

.PARAMETER Yes
    Skip the confirmation. For a rehearsal script; not for the morning of.

.EXAMPLE
    .\scripts\demo-reset.ps1 -Preview

.EXAMPLE
    .\scripts\demo-reset.ps1 -IncludeUsers

.NOTES
    Windows PowerShell 5.1 and PowerShell 7. Docker Desktop only.

    Exit codes
        0   done
        1   something failed
        3   refused - you did not confirm
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Preview,
    [switch]$IncludeUsers,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

# -WhatIf is PowerShell's own word for the same thing, so both work and
# neither can mean something different from the other.
$previewOnly = $Preview.IsPresent -or ($PSBoundParameters.ContainsKey('WhatIf'))

Write-Host ''
Write-Host 'CreditProbe - demonstration workspace reset' -ForegroundColor White

$running = & docker compose ps --format '{{.Service}} {{.State}}' 2>&1
if ($LASTEXITCODE -ne 0 -or -not ($running -match 'backend\s+running')) {
    Write-Host ''
    Write-Host 'The backend container is not running. Start it first:' -ForegroundColor Red
    Write-Host '    .\scripts\demo-start.ps1' -ForegroundColor White
    Pop-Location
    exit 1
}

$arguments = @('compose', 'exec', '-T', 'backend', 'python', 'scripts/demo_state.py')

if ($previewOnly) {
    $arguments += '--preview'
    if ($IncludeUsers) { $arguments += '--include-users' }
    Write-Host '  PREVIEW - nothing will be changed.' -ForegroundColor Yellow
    & docker @arguments
    Pop-Location
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host '  This removes the demonstration workspace and rebuilds it.' -ForegroundColor Yellow
Write-Host '  Governed data, the teaching library, approved releases and user' -ForegroundColor Gray
Write-Host '  credentials are NOT touched.' -ForegroundColor Gray
if ($IncludeUsers) {
    Write-Host '  The ten test accounts will also be removed. The four' -ForegroundColor Gray
    Write-Host '  demonstration accounts are kept.' -ForegroundColor Gray
}
Write-Host ''
Write-Host '  Run with -Preview first if you want to see the row counts.' -ForegroundColor DarkGray

if (-not $Yes) {
    $answer = Read-Host '  Type ''yes'' to continue'
    if ($answer -ne 'yes') {
        Write-Host '  Nothing was changed.' -ForegroundColor Gray
        Pop-Location
        exit 3
    }
}

$arguments += @('--rebuild', '--yes')
if ($IncludeUsers) { $arguments += '--include-users' }

& docker @arguments
$code = $LASTEXITCODE

Write-Host ''
if ($code -eq 0) {
    Write-Host 'The demonstration workspace is back to its known state.' -ForegroundColor Green
    Write-Host '  Check it with:  .\scripts\demo-check.ps1' -ForegroundColor Gray
}
else {
    Write-Host 'The reset did not finish. The reason is above.' -ForegroundColor Red
}

Pop-Location
exit $code
