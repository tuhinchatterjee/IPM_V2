#Requires -Version 5.1
<#
.SYNOPSIS
    Verify that the CreditProbe build you are running really does talk to the
    live Anthropic model.

.DESCRIPTION
    Every automated gate in this repository runs without a provider key. That
    is correct - the deterministic governed reader has to work on its own - but
    it means a green suite proves nothing whatever about the live path. A
    product that shows "AI POWERED" on the strength of a test that never called
    a model is making a claim it has not earned.

    Your key never leaves this machine, so the verification has to run here.
    This script drives the verification INSIDE the running backend container,
    which already receives ANTHROPIC_API_KEY at run time from your .env through
    docker-compose.

    Nothing needs to be installed except Docker Desktop. No Python, no Node.js.

.NOTES
    THIS FILE IS DELIBERATELY PURE ASCII
    ------------------------------------
    Windows PowerShell 5.1 reads a .ps1 with no byte order mark using the
    system ANSI code page, not UTF-8. On a Western install that is CP1252, so
    the three UTF-8 bytes of an em dash (E2 80 94) decode as "a-circumflex",
    "euro sign", and U+201D RIGHT DOUBLE QUOTATION MARK. PowerShell's tokenizer
    accepts U+201D as a closing double quote, so one em dash inside a
    double-quoted string ended that string early, the real quote then opened a
    new one, and the parser ran to the end of the file before reporting

        The string is missing the terminator: ".

    at a line hundreds of lines below the actual fault. Keeping this file to
    ASCII removes the whole class: every code page agrees on bytes 0x00-0x7F.
    tests/scripts/test_powershell_script.py enforces it.

    THE KEY
    -------
    This script never reads, prints, logs or writes your API key. It does not
    pass it as a Docker build argument - a build argument is baked into an
    image layer and travels with the image. It is injected at RUN time by
    docker-compose from .env, which is gitignored, and the verification asks
    the provider only whether a key is *present*.

    COST
    ----
    -DryRun, -FeedbackCritical and -RegulatoryCritical spend nothing: those
    three paths are entirely deterministic and make no provider call at all.
    Every other mode makes real provider calls and consumes credit; each
    prints its estimate before it runs and, unless you pass -Yes, asks you to
    confirm.

    EXIT CODES
    ----------
    These are a contract shared with backend/validation/live_verify.py. A run
    whose calls passed but whose report could not be stored is NOT a success:
    nothing can be bound to the build, and the product will not show durable
    verification.

        0   LIVE_VERIFIED, DETERMINISTIC_VERIFIED or DRY_RUN
        1   FAILED               a case did not pass
        2   PASSED_NOT_STORED    calls passed, report refused or unwritable
        3   NOT_ELIGIBLE         no key, or the image is not this commit

    DETERMINISTIC_VERIFIED is not a synonym for LIVE_VERIFIED and never
    lights the AI panel's LIVE VERIFIED lamp. It means every check in a mode
    that makes no provider call passed. Reporting it as a live verification
    would claim a model ran when none did.

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
    application and the product may not import it - a product that can reach
    its own exam has no exam - so certifying against it is a build-time command
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

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -AgenticCritical

    .\scripts\verify-live-ai.ps1 -BrainImport

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -FeedbackCritical

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -RegulatoryCritical

.EXAMPLE
    .\scripts\verify-live-ai.ps1 -ProjectCritical
#>

[CmdletBinding(DefaultParameterSetName = 'DryRun')]
param(
    [Parameter(ParameterSetName = 'DryRun')][switch]$DryRun,
    [Parameter(ParameterSetName = 'Quick')][switch]$Quick,
    [Parameter(ParameterSetName = 'Critical')][switch]$Critical,
    [Parameter(ParameterSetName = 'FullRouting')][switch]$FullRouting,
    [Parameter(ParameterSetName = 'FullCertification')][switch]$FullCertification,
    # The final consolidation phase's four narrow modes. Each drives one area
    # end to end rather than sampling across all of them, because "the
    # agentic layer is broken" and "the feedback loop is broken" need
    # different evidence and a mixed run gives neither.
    [Parameter(ParameterSetName = 'AgenticCritical')][switch]$AgenticCritical,
    [Parameter(ParameterSetName = 'FeedbackCritical')][switch]$FeedbackCritical,
    [Parameter(ParameterSetName = 'RegulatoryCritical')][switch]$RegulatoryCritical,
    [Parameter(ParameterSetName = 'ProjectCritical')][switch]$ProjectCritical,
    # Section 52's Brain import evaluation. Deterministic, and that is not a
    # shortcut: the Lift Lab compares recorded scores against recorded
    # scores. Running a model to decide whether an imported Brain helped
    # would measure the model, not the Brain.
    [Parameter(ParameterSetName = 'BrainImport')][switch]$BrainImport,
    [switch]$Yes,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

# Version 2.0 rather than Latest: Latest means different things on Windows
# PowerShell 5.1 and on PowerShell 7, and a script that behaves differently on
# the two is exactly what this file exists to avoid.
Set-StrictMode -Version 2.0

# Defined before anything can read it. Under StrictMode an unset variable
# throws, and $LASTEXITCODE does not exist until a native command has run.
$LASTEXITCODE = 0

# The repository root, from this script's own location, so the script works
# from any working directory.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -Path $RepoRoot

# What each mode roughly costs. Repeated here as well as in the Python module
# so the number is on screen BEFORE anything is started. A tool that tells you
# what a run cost afterwards is a tool people stop running.
$EstimatedCalls = @{
    'dryrun'             = 0
    'quick'              = 13
    'critical'           = 30
    'fullrouting'        = 14
    'fullcertification'  = 120
    'agenticcritical'    = 22
    # Zero, and it is not a rounding. The feedback and regulatory paths are
    # entirely deterministic: recording a rating, labelling an observation,
    # proposing a candidate, extracting a circular and retrieving as of a date
    # all run without a model. A mode that reported "about 5 calls" for them
    # would be describing a system that does not exist.
    'feedbackcritical'   = 0
    'regulatorycritical' = 0
    'projectcritical'    = 18
    'brainimport'        = 0
}

# The exit-code contract, shared with backend/validation/live_verify.py.
$ExitLiveVerified   = 0
$ExitFailed         = 1
$ExitPassedNotStored = 2
$ExitNotEligible    = 3

function Write-Head {
    param([string]$Text)
    Write-Host ''
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('-' * $Text.Length) -ForegroundColor DarkGray
}

function Write-Field {
    param(
        [string]$Label,
        [string]$Value,
        [string]$Colour = 'Gray'
    )
    Write-Host ('  {0,-22}' -f $Label) -NoNewline
    Write-Host $Value -ForegroundColor $Colour
}

function Stop-With {
    param([string]$Message, [int]$Code)
    Write-Host ''
    Write-Host ('  {0}' -f $Message) -ForegroundColor Red
    Pop-Location
    exit $Code
}

# --------------------------------------------------------------- which mode

$Mode = 'dryrun'
switch ($PSCmdlet.ParameterSetName) {
    'Quick'              { $Mode = 'quick' }
    'Critical'           { $Mode = 'critical' }
    'FullRouting'        { $Mode = 'fullrouting' }
    'FullCertification'  { $Mode = 'fullcertification' }
    'AgenticCritical'    { $Mode = 'agenticcritical' }
    'FeedbackCritical'   { $Mode = 'feedbackcritical' }
    'BrainImport'        { $Mode = 'brainimport' }
    'RegulatoryCritical' { $Mode = 'regulatorycritical' }
    'ProjectCritical'    { $Mode = 'projectcritical' }
}

Write-Head ('CreditProbe live AI verification - {0}' -f $Mode)

# ------------------------------------------------------------ the local repo
#
# Read on the host rather than in the container: what matters is whether the
# image was built from the commit you are looking at, and only the host can
# answer half of that.

$Sha = 'unknown'
$Branch = 'unknown'
$Dirty = $false

$GitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($null -ne $GitCommand) {
    try {
        $RawSha = & git rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $null -ne $RawSha) {
            $Sha = ([string]$RawSha).Trim()
        }
        $RawBranch = & git rev-parse --abbrev-ref HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $null -ne $RawBranch) {
            $Branch = ([string]$RawBranch).Trim()
        }
        $RawStatus = & git status --porcelain 2>$null
        $Dirty = -not [string]::IsNullOrWhiteSpace(($RawStatus | Out-String))
    }
    catch {
        Write-Host '  (git is present but this is not a repository)' -ForegroundColor DarkYellow
    }
}

$ShortSha = 'unknown'
if ($Sha -ne 'unknown' -and $Sha.Length -ge 12) {
    $ShortSha = $Sha.Substring(0, 12)
}

$TreeState = 'clean'
$TreeColour = 'Gray'
if ($Dirty) {
    $TreeState = 'DIRTY - uncommitted changes'
    $TreeColour = 'Yellow'
}

Write-Field 'branch' $Branch
Write-Field 'commit' $ShortSha
Write-Field 'working tree' $TreeState $TreeColour

# ---------------------------------------------------------------- the .env
#
# Presence only. This script never reads a value out of it, and never prints
# one. Absence is worth saying out loud because it is the commonest reason a
# live mode cannot run.

$EnvPath = Join-Path -Path $RepoRoot -ChildPath '.env'
if (Test-Path -LiteralPath $EnvPath) {
    # Whether the file NAMES the variable. The value is never read.
    $Names = Select-String -LiteralPath $EnvPath -Pattern '^\s*ANTHROPIC_API_KEY\s*=' -Quiet
    if ($Names) {
        Write-Field '.env' 'present, names ANTHROPIC_API_KEY'
    }
    else {
        Write-Field '.env' 'present, does not name ANTHROPIC_API_KEY' 'Yellow'
    }
}
else {
    Write-Field '.env' 'not found - copy .env.example and add your key' 'Yellow'
}

# ----------------------------------------------------------------- Docker

$DockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $DockerCommand) {
    Stop-With 'Docker was not found. Install Docker Desktop and start it, then run this again.' $ExitNotEligible
}

$null = & docker version --format '{{.Server.Version}}' 2>&1
if ($LASTEXITCODE -ne 0) {
    Stop-With 'Docker is installed but not running. Start Docker Desktop and run this again.' $ExitNotEligible
}
Write-Field 'docker' 'running'

# The backend container has to be up: the key is injected into it at run time,
# so verification happens inside it and nowhere else.
$RunningRaw = & docker compose ps --status running --format '{{.Service}}' 2>&1
$Running = @()
if ($LASTEXITCODE -eq 0 -and $null -ne $RunningRaw) {
    $Running = @(($RunningRaw | Out-String) -split "`r?`n" |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_.Length -gt 0 })
}

if ($Running -notcontains 'backend') {
    Write-Host ''
    Write-Host '  The backend container is not running.' -ForegroundColor Yellow
    Write-Host '  Start the stack first:' -ForegroundColor Gray
    Write-Host '      docker compose up -d --build' -ForegroundColor White
    Pop-Location
    exit $ExitNotEligible
}
Write-Field 'backend container' 'running'

# ---------------------------------------------------- cost, and consent

$Calls = 0
if ($EstimatedCalls.ContainsKey($Mode)) {
    $Calls = $EstimatedCalls[$Mode]
}

if ($Calls -eq 0) {
    Write-Field 'estimated calls' '0 - this mode spends nothing' 'Green'
}
else {
    Write-Field 'estimated calls' ('{0} (approximate)' -f $Calls) 'Yellow'
}

if ($Calls -gt 0 -and -not $Yes) {
    Write-Host ''
    Write-Host '  This mode makes real Anthropic calls and consumes credit.' -ForegroundColor Yellow
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
if ($Json) {
    $Arguments += '--json'
}

# "docker compose exec" with -T keeps stdin closed, which is what makes this
# usable from a script and from CI. The container already holds the key; it is
# never passed on this command line, where it would land in the shell history
# and in the process table.
& docker @Arguments
$Code = $LASTEXITCODE

# ------------------------------------------------------------- the report

Write-Head 'Report'

# A run that makes no provider call writes to its OWN file. One report per
# commit was fine while every mode was a live one; it meant the cheapest
# command in the product could land on top of - and destroy - the report a
# paid run had just written. Kept in step with `report_name()` in
# backend/validation/live_verify.py.
$DeterministicModes = @('dryrun', 'feedbackcritical', 'regulatorycritical', 'brainimport')
if ($DeterministicModes -contains $Mode) {
    $ReportName = 'verification_{0}_{1}.json' -f $Mode, $ShortSha
}
else {
    $ReportName = 'live_ai_verification_{0}.json' -f $ShortSha
}
$LogDirectory = Join-Path -Path $RepoRoot -ChildPath 'logs'
$ReportPath = Join-Path -Path $LogDirectory -ChildPath $ReportName

$ReportExists = Test-Path -LiteralPath $ReportPath
if ($ReportExists) {
    Write-Field 'written to' $ReportPath
    Write-Host '  The report contains no key, no authorization header, no raw' -ForegroundColor DarkGray
    Write-Host '  prompt, no benchmark answers and no client data rows.' -ForegroundColor DarkGray
}
else {
    Write-Field 'written to' 'no report file was produced' 'Yellow'
}

# ------------------------------------------------------------- the verdict
#
# The exit code from the container is the authority. It already distinguishes
# "the calls passed and the report was stored" from "the calls passed and the
# report was refused", and the second is not a success: nothing can be bound to
# the build, and the product will not show durable verification.

$Status = 'UNKNOWN'
switch ($Code) {
    0 { $Status = 'LIVE_VERIFIED' }
    1 { $Status = 'FAILED' }
    2 { $Status = 'PASSED_NOT_STORED' }
    3 { $Status = 'NOT_ELIGIBLE' }
}
if ($Code -eq 0 -and $DeterministicModes -contains $Mode) {
    $Status = $(if ($Mode -eq 'dryrun') { 'DRY_RUN' }
                else { 'DETERMINISTIC_VERIFIED' })
}

Write-Field 'status' $Status $(if ($Code -eq 0) { 'Green' } else { 'Red' })

if ($Status -eq 'DRY_RUN') {
    Write-Host ''
    Write-Host '  Dry run complete. Nothing was spent.' -ForegroundColor Green
    Write-Host '  To verify for real:' -ForegroundColor Gray
    Write-Host '      .\scripts\verify-live-ai.ps1 -Quick' -ForegroundColor White
}
elseif ($Status -eq 'DETERMINISTIC_VERIFIED') {
    Write-Host ''
    Write-Host '  Every check passed and the report was stored.' -ForegroundColor Green
    Write-Host '  This mode made NO provider call, so it is not live-model' -ForegroundColor Gray
    Write-Host '  verification and the AI panel will not show LIVE VERIFIED.' -ForegroundColor Gray
    Write-Host '  It verifies deterministic behaviour: the feedback prompt,' -ForegroundColor DarkGray
    Write-Host '  the learning pipeline and the regulatory gates.' -ForegroundColor DarkGray
}
elseif ($Status -eq 'LIVE_VERIFIED') {
    Write-Host ''
    Write-Host '  Verification passed and the report was stored.' -ForegroundColor Green
    Write-Host '  The AI panel will now show LIVE VERIFIED for this commit.' -ForegroundColor Gray
    Write-Host '  This confirms the live model path ran and conformed on the' -ForegroundColor DarkGray
    Write-Host '  cases listed. It is not a measure of accuracy.' -ForegroundColor DarkGray
}
elseif ($Status -eq 'PASSED_NOT_STORED') {
    Write-Host ''
    Write-Host '  The live calls PASSED, but the report could not be stored.' -ForegroundColor Yellow
    Write-Host '  This is not a complete verification:' -ForegroundColor Yellow
    Write-Host '    - nothing is bound to this commit or model configuration' -ForegroundColor Gray
    Write-Host '    - the AI panel will NOT show LIVE VERIFIED' -ForegroundColor Gray
    Write-Host '    - the result cannot be audited later' -ForegroundColor Gray
    Write-Host '  The reason is printed above. Fix it and run this again.' -ForegroundColor Gray
}
elseif ($Status -eq 'NOT_ELIGIBLE') {
    Write-Host ''
    Write-Host '  This build cannot be live verified yet. The reason is above.' -ForegroundColor Yellow
    Write-Host '  Usually: no key in .env, or the image was built from a' -ForegroundColor Gray
    Write-Host '  different commit than the one checked out. Rebuild with:' -ForegroundColor Gray
    Write-Host '      docker compose up -d --build' -ForegroundColor White
}
else {
    Write-Host ''
    Write-Host '  Verification did not pass. See the cases above.' -ForegroundColor Red
}

Pop-Location
exit $Code
