<#
.SYNOPSIS
    Stop the CreditProbe demonstration stack.

.DESCRIPTION
    Stops the containers and keeps everything: the database volume, the demo
    workspace, the .env and every stored report.

    The destructive option is deliberately NOT here. `docker compose down -v`
    destroys the database volume, and a flag that did that would sit one
    keystroke away from the flag that does not. Use demo-reset.ps1, which
    rebuilds the workspace and asks first.

.PARAMETER KeepDatabase
    Stop the application containers and leave the database running. Useful
    between rehearsals: the next start is much faster.

.EXAMPLE
    .\scripts\demo-stop.ps1

.EXAMPLE
    .\scripts\demo-stop.ps1 -KeepDatabase

.NOTES
    Windows PowerShell 5.1 and PowerShell 7. Docker Desktop only.
#>
[CmdletBinding()]
param(
    [switch]$KeepDatabase
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

Write-Host ''
Write-Host 'CreditProbe - stopping the demonstration stack' -ForegroundColor White

if ($KeepDatabase) {
    Write-Host '  stopping backend, frontend and agent-worker; leaving the database up ...'
    & docker compose stop backend frontend agent-worker
}
else {
    Write-Host '  stopping every service ...'
    & docker compose stop
}

if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'Something did not stop cleanly. Check: docker compose ps' -ForegroundColor Yellow
    Pop-Location
    exit 1
}

Write-Host ''
Write-Host 'Stopped. Nothing was deleted.' -ForegroundColor Green
Write-Host '  The database volume, the demonstration workspace, your .env and' -ForegroundColor DarkGray
Write-Host '  every stored verification report are all still there.' -ForegroundColor DarkGray
Write-Host ''
Write-Host '  Start again with:  .\scripts\demo-start.ps1' -ForegroundColor Gray

Pop-Location
exit 0
