#Requires -Version 5.1
<#
.SYNOPSIS
    Verify that the CreditProbe build you are running really does talk to the
    live Anthropic model.

.DESCRIPTION
    Every automated gate in this repository runs without a provider key. That
    is correct — the deterministic governed reader has to work on its own — but
    it means a green suite proves nothing whatever about the live path. A
    product that shows "AI POWERED" on the strength of a test that never called
    a model is making a claim it has not earned.

    Your key never leaves this machine, so the verification has to run here.
    This script drives the verification INSIDE the running backend container,
    which already receives ANTHROPIC_API_KEY at run time from your .env through
    docker-compose.

    Nothing needs to be installed except Docker Desktop. No Python, no Node.js.

.NOTES
    THE KEY
    -------
    This script never reads, prints, logs or writes your API key. It does not
    pass it as a Docker build argument — a build argument is baked into an image
    layer and travels with the image. It is injected at RUN time by
    docker-compose from .env, which is gitignored, and the verification asks the
    provider only whether a key is *present*.

    COST
    ----
    -DryRun spends nothing. Every other mode makes real provider calls and
    consumes credit; each prints its estimate before it runs and, unless you
    pass -Yes, asks you to confirm.

.PARAMETER DryRun
    Report what would be verified, and what each mode would cost. Zero credits.

.PARAMETER Quick
    One tiny schema-constrained call for each configured model role, then the
    live smoke suite. Stops at the first role that cannot be served.

.PARAMETER Critical
    The seven end-to-end conversation threads, through the same API the browser
    uses: metadata memory, a complex dynamic calculation, entity-set memory,
    previous-result reuse, material ambiguity, the business-invariant gate, and
    an unsupported request.

.PARAMETER FullRouting
    The complete live intent-recognition suite.

.PARAMETER FullCertification
    The whole shipped benchmark library, scored against the live model. The
    most expensive mode by a wide margin.

    This is NOT the sealed certification. The sealed holdout lives outside the
    application and the product may not import it — a product that can reach
    its own exam has no exam — so certifying against it is a build-time command
    run from the repository, not a mode of a tool that runs inside a container.

.PARAMETER Yes
    Skip the confirmation prompt. For a mode that spends credit, you are saying
    you have read the estimate.

.PARAMETER Json
    Print the whole report as JSON instead of a summary.

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -DryRun

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -Quick

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -Critical

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -FullRouting
#>

[CmdletBinding(DefaultParameterSetName = 'DryRun')]
param(
    [Parameter(ParameterSetName = 'DryRun')][switch]$DryRun,
    [Parameter(ParameterSetName = 'Quick')][switch]$Quick,
    [Parameter(ParameterSetName = 'Critical')][switch]$Critical,
    [Parameter(ParameterSetName = 'FullRouting')][switch]$FullRouting,
    [Parameter(ParameterSetName = 'FullCertification')][switch]$FullCertification,
    [switch]$Yes,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# The repository root, from this script's own location, so the script works
# from any working directory.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

# What each mode roughly costs. Repeated here as well as in the Python module
# so the number is on screen BEFORE anything is started — a tool that tells you
# what a run cost afterwards is a tool people stop running.
$EstimatedCalls = @{
    'dryrun'            = 0
    'quick'             = 12
    'critical'          = 30
    'fullrouting'       = 14
    'fullcertification' = 120
}

function Write-Head([string]$Text) {
    Write-Host ''
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('-' * $Text.Length) -ForegroundColor DarkGray
}

function Write-Field([string]$Label, [string]$Value, [string]$Colour = 'Gray') {
    Write-Host ('  {0,-22}' -f $Label) -NoNewline
    Write-Host $Value -ForegroundColor $Colour
}

function Fail([string]$Message) {
    Write-Host ''
    Write-Host "  $Message" -ForegroundColor Red
    Pop-Location
    exit 1
}

# --------------------------------------------------------------- which mode

$Mode = switch ($PSCmdlet.ParameterSetName) {
    'Quick'             { 'quick' }
    'Critical'          { 'critical' }
    'FullRouting'       { 'fullrouting' }
    'FullCertification' { 'fullcertification' }
    default             { 'dryrun' }
}

Write-Head "CreditProbe live AI verification — $Mode"

# ------------------------------------------------------------ the local repo
#
# Read on the host rather than in the container: what matters is whether the
# image was built from the commit you are looking at, and only the host can
# answer half of that.

$Sha = 'unknown'; $Branch = 'unknown'; $Dirty = $false
if (Get-Command git -ErrorAction SilentlyContinue) {
    try {
        $Sha = (git rev-parse HEAD 2>$null).Trim()
        $Branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
        $Dirty = -not [string]::IsNullOrWhiteSpace((git status --porcelain 2>$null))
    } catch {
        Write-Host '  (git is present but this is not a repository)' -ForegroundColor DarkYellow
    }
}

Write-Field 'branch' $Branch
Write-Field 'commit' $(if ($Sha -ne 'unknown') { $Sha.Substring(0, 12) } else { $Sha })
Write-Field 'working tree' $(if ($Dirty) { 'DIRTY — uncommitted changes' } else { 'clean' }) `
    $(if ($Dirty) { 'Yellow' } else { 'Gray' })

# ---------------------------------------------------------------- the .env
#
# Presence only. This script never reads a value out of it, and never prints
# one. Absence is worth saying out loud because it is the commonest reason a
# live mode cannot run.

$EnvPath = Join-Path $RepoRoot '.env'
if (Test-Path $EnvPath) {
    # Whether the file MENTIONS the variable. The value is never read.
    $Mentions = Select-String -Path $EnvPath -Pattern '^\s*ANTHROPIC_API_KEY\s*=' -Quiet
    Write-Field '.env' $(if ($Mentions) { 'present, names ANTHROPIC_API_KEY' } else { 'present, does not name ANTHROPIC_API_KEY' }) `
        $(if ($Mentions) { 'Gray' } else { 'Yellow' })
} else {
    Write-Field '.env' 'not found — copy .env.example and add your key' 'Yellow'
}

# ----------------------------------------------------------------- Docker

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail 'Docker was not found. Install Docker Desktop and start it, then run this again.'
}

try {
    docker version --format '{{.Server.Version}}' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'no daemon' }
} catch {
    Fail 'Docker is installed but not running. Start Docker Desktop and run this again.'
}
Write-Field 'docker' 'running'

# The backend container has to be up: the key is injected into it at run time,
# so verification happens inside it and nowhere else.
$Running = (docker compose ps --status running --format '{{.Service}}' 2>$null) -split "`n" |
    ForEach-Object { $_.Trim() } | Where-Object { $_ }
if ($Running -notcontains 'backend') {
    Write-Host ''
    Write-Host '  The backend container is not running.' -ForegroundColor Yellow
    Write-Host '  Start the stack first:' -ForegroundColor Gray
    Write-Host '      docker compose up -d --build' -ForegroundColor White
    Pop-Location
    exit 1
}
Write-Field 'backend container' 'running'

# ---------------------------------------------------- cost, and consent

$Calls = $EstimatedCalls[$Mode]
Write-Field 'estimated calls' $(if ($Calls -eq 0) { '0 — this mode spends nothing' } else { "$Calls (approximate)" }) `
    $(if ($Calls -eq 0) { 'Green' } else { 'Yellow' })

if ($Calls -gt 0 -and -not $Yes) {
    Write-Host ''
    Write-Host "  This mode makes real Anthropic calls and consumes credit." -ForegroundColor Yellow
    $Answer = Read-Host '  Continue? [y/N]'
    if ($Answer -notmatch '^(y|yes)$') {
        Write-Host '  Nothing was run.' -ForegroundColor Gray
        Pop-Location
        exit 0
    }
}

# ------------------------------------------------------------- run it

Write-Head 'Running inside the backend container'

$Arguments = @(
    'compose', 'exec', '-T', 'backend',
    'python', '-m', 'backend.validation.live_verify',
    '--mode', $Mode
)
if ($Json) { $Arguments += '--json' }

# `docker compose exec` with -T keeps stdin closed, which is what makes this
# usable from a script and from CI. The container already holds the key; it is
# never passed on this command line, where it would land in the shell history
# and in the process table.
& docker @Arguments
$Code = $LASTEXITCODE

# ------------------------------------------------------------- the report

Write-Head 'Report'

$Short = if ($Sha -ne 'unknown') { $Sha.Substring(0, 12) } else { 'unknown' }
$ReportPath = Join-Path $RepoRoot "logs\live_ai_verification_$Short.json"

if (Test-Path $ReportPath) {
    Write-Field 'written to' $ReportPath
    Write-Host '  The report contains no key, no authorization header, no raw' -ForegroundColor DarkGray
    Write-Host '  prompt, no benchmark answers and no client data rows.' -ForegroundColor DarkGray
} else {
    Write-Field 'written to' 'no report file was produced' 'Yellow'
}

if ($Code -eq 0) {
    if ($Mode -eq 'dryrun') {
        Write-Host ''
        Write-Host '  Dry run complete. Nothing was spent.' -ForegroundColor Green
        Write-Host '  To verify for real:' -ForegroundColor Gray
        Write-Host '      .\scripts\verify-live-ai.ps1 -Quick' -ForegroundColor White
    } else {
        Write-Host ''
        Write-Host '  Verification passed.' -ForegroundColor Green
        Write-Host '  This confirms the live model path ran and conformed on the' -ForegroundColor DarkGray
        Write-Host '  cases listed. It is not a measure of accuracy.' -ForegroundColor DarkGray
    }
} else {
    Write-Host ''
    Write-Host '  Verification did not pass. See the cases above.' -ForegroundColor Red
}

Pop-Location
exit $Code
