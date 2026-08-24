# Stop CreditProbe.
#
#     .\scripts\stop-docker.ps1
#
# Your database is kept, so the next start is quick and your saved
# investigations are still there.
#
# To erase the database as well and start completely fresh:
#
#     .\scripts\stop-docker.ps1 -EraseData

param(
    [switch]$EraseData
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if ($EraseData) {
    Write-Host ""
    Write-Host "This will permanently erase the CreditProbe database:" -ForegroundColor Yellow
    Write-Host "  saved investigations, traces, and anything created in Data Builder."
    Write-Host "  The analytical Parquet data under data\ is NOT affected."
    Write-Host ""
    $answer = Read-Host "Type ERASE to confirm"
    if ($answer -ne "ERASE") {
        Write-Host "Cancelled. Nothing was erased." -ForegroundColor Green
        exit 0
    }
    docker compose down -v
    Write-Host ""
    Write-Host "  CreditProbe stopped and the database erased." -ForegroundColor Green
} else {
    docker compose down
    Write-Host ""
    Write-Host "  CreditProbe stopped. Your data is kept." -ForegroundColor Green
    Write-Host "  Start it again with:  .\scripts\start-docker.ps1" -ForegroundColor DarkGray
}
Write-Host ""
