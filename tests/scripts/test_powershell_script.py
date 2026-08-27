"""
The Windows entry points, checked by something other than "it looks fine".

The failure these exist for
---------------------------
`scripts/verify-live-ai.ps1` shipped in a state Windows PowerShell 5.1 could
not parse at all:

    The string is missing the terminator: ".

Nothing in this repository noticed. Every Linux tool read the file perfectly,
the reported line number pointed at a line that was valid, and the actual fault
was two hundred lines earlier and invisible in the source: the file was UTF-8
with no byte order mark, PowerShell 5.1 reads such a file as the system ANSI
code page, and the three bytes of an em dash decode under CP1252 into a
character PowerShell accepts as a closing double quote.

So the rule these tests enforce is not "no em dashes" as a style preference.
It is that a `.ps1` in this repository must be pure ASCII, because ASCII is the
only range every code page agrees on.

What can and cannot be claimed
------------------------------
There is no PowerShell runtime in this environment. Where one exists these
tests ask PowerShell's own parser, which is the only real authority. Where one
does not, they run a tokenizer that models PowerShell's string rules — and the
test below proves that tokenizer reproduces the exact failure that shipped,
so it is a floor rather than a hope.

Windows compatibility is NOT claimed on the strength of a Linux run. See
`test_the_runtime_check_is_honest_about_its_own_absence`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
VERIFY = SCRIPTS / "verify-live-ai.ps1"

sys.path.insert(0, str(SCRIPTS))

from check_powershell import (  # noqa: E402 - the checker lives beside the scripts
    SMART_QUOTES,
    STRICT,
    Unterminated,
    check,
    check_source,
    check_with_powershell,
    code_only,
    powershell,
)


def all_scripts() -> list[Path]:
    return sorted(SCRIPTS.glob("*.ps1"))


# ---------------------------------------------------------------- the parser


@pytest.mark.parametrize("path", all_scripts(), ids=lambda p: p.name)
def test_every_powershell_script_parses(path: Path):
    """Zero problems, at every level the checker can reach."""
    problems = check(path)
    assert not problems, "\n".join(str(p) for p in problems)


def test_the_verification_script_is_held_to_the_full_policy():
    assert VERIFY.name in STRICT
    assert not check(VERIFY, strict=True)


@pytest.mark.skipif(not powershell(),
                    reason="No PowerShell runtime in this environment.")
@pytest.mark.parametrize("path", all_scripts(), ids=lambda p: p.name)
def test_powershells_own_parser_accepts_it(path: Path):
    """The only authority that matters, when there is one to ask."""
    problems = check_with_powershell(path)
    assert not problems, "\n".join(str(p) for p in problems)


def test_the_runtime_check_is_honest_about_its_own_absence():
    """`check_with_powershell` returns nothing when it cannot look.

    An empty list means "no problems found", and with no runtime that is not
    the same statement. The caller has to consult `powershell()` to tell them
    apart, and this pins that contract so nobody later reads a green run on
    Linux as proof about Windows.
    """
    assert check_with_powershell(VERIFY, executable="") == []


# -------------------------------------------------------------- the encoding


@pytest.mark.parametrize("path", all_scripts(), ids=lambda p: p.name)
def test_every_powershell_script_is_pure_ascii(path: Path):
    """The rule that would have caught the shipped defect."""
    raw = path.read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not offenders, (
        f"{path.name} has {len(offenders)} non-ASCII byte(s), the first at "
        f"offset {offenders[0][0]} (0x{offenders[0][1]:02X}). Windows "
        "PowerShell 5.1 reads a BOM-less .ps1 as the system ANSI code page, "
        "so these do not mean on Windows what they mean here.")


@pytest.mark.parametrize("path", all_scripts(), ids=lambda p: p.name)
def test_no_powershell_script_carries_a_byte_order_mark(path: Path):
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("path", all_scripts(), ids=lambda p: p.name)
def test_no_smart_quotes(path: Path):
    text = path.read_text(encoding="utf-8")
    present = sorted({ch for ch in text if ch in SMART_QUOTES})
    assert not present, (
        f"{path.name} contains {present}, which PowerShell accepts as string "
        "delimiters")


def test_the_tokenizer_reproduces_the_failure_that_shipped():
    """The proof that the source check is a floor and not a hope.

    This is the file as Windows PowerShell 5.1 actually decoded it: the em
    dash's UTF-8 bytes read through CP1252. If the tokenizer cannot see the
    unterminated string here, it could not have caught the bug, and these tests
    would be decoration.
    """
    mojibake = b"\xe2\x80\x94".decode("cp1252")
    assert mojibake.endswith("”"), "CP1252 turns the em dash into a quote"

    shipped = (
        'Write-Head "CreditProbe live AI verification ' + mojibake + ' $Mode"\n'
        'Write-Host "and everything after it"\n'
    )
    with pytest.raises(Unterminated) as raised:
        code_only(shipped)
    assert "double-quoted string" in str(raised.value)


def test_a_clean_script_tokenizes():
    text = VERIFY.read_text(encoding="utf-8")
    code = code_only(text)
    assert len(code) == len(text), "blanking must not move any line"
    # The help block is a comment, so its prose is not code.
    assert "SYNOPSIS" not in code
    # ...and the actual commands are.
    assert "docker" in code


# ------------------------------------------------------- version compatibility


@pytest.mark.parametrize("snippet,expected", [
    ("$x = $a ?? $b", "null-coalescing"),
    ("$x = $a?.Length", "null-conditional"),
    ("Get-Thing && Set-Thing", "pipeline chain"),
    ("Get-Thing || Set-Thing", "pipeline chain"),
    ("1..3 | ForEach-Object -Parallel { $_ }", "Parallel"),
    ("Set-StrictMode -Version Latest", "different things on 5.1 and 7"),
])
def test_powershell_7_only_syntax_is_refused(snippet: str, expected: str):
    text = f"#Requires -Version 5.1\n{snippet}\n"
    problems = check_source(text, Path("x.ps1"), strict=True)
    assert any(expected in p.detail for p in problems), (
        f"{snippet!r} was accepted; got {[str(p) for p in problems]}")


def test_the_same_syntax_inside_a_comment_is_allowed():
    """A script may describe syntax it does not use.

    The verification script's own help text names PowerShell 7 features in
    order to explain why it avoids them, and a checker that could not tell a
    comment from a command would make that impossible to write down.
    """
    text = ("#Requires -Version 5.1\n"
            "# Do not use $a ?? $b or Get-Thing && Set-Thing here.\n"
            "Write-Host 'the ?? operator is PowerShell 7 only'\n")
    assert not check_source(text, Path("x.ps1"), strict=True)


def test_the_script_declares_the_version_it_supports():
    text = VERIFY.read_text(encoding="utf-8")
    assert text.splitlines()[0].strip() == "#Requires -Version 5.1"


def test_strict_mode_is_pinned_to_a_number():
    text = VERIFY.read_text(encoding="utf-8")
    assert "Set-StrictMode -Version 2.0" in text
    assert "Set-StrictMode -Version Latest" not in text


# ------------------------------------------------------------------- secrets


@pytest.mark.parametrize("path", all_scripts(), ids=lambda p: p.name)
def test_no_powershell_script_embeds_a_secret(path: Path):
    assert not [p for p in check(path) if p.kind == "secret"]


@pytest.mark.parametrize("secret", [
    "sk-ant-api03-notarealkeybutshaped",
    "sk_live_abcdefghijklmnop",
    "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
    "ANTHROPIC_API_KEY=sk-ant-something",
])
def test_a_committed_secret_is_refused(secret: str):
    text = f"#Requires -Version 5.1\nWrite-Host '{secret}'\n"
    problems = check_source(text, Path("x.ps1"), strict=True)
    assert any(p.kind == "secret" for p in problems), (
        f"{secret!r} was accepted")


def test_the_script_never_reads_the_key_only_whether_it_is_named():
    """The zero-secret guarantee, as a property of the source.

    The script may check that .env NAMES the variable. It may never read a
    value out of it, echo it, or put it on a command line where it would land
    in the shell history and the process table.
    """
    text = VERIFY.read_text(encoding="utf-8")
    assert "-Quiet" in text, "the .env check must not capture the value"
    assert "$env:ANTHROPIC_API_KEY" not in text
    assert "--build-arg" not in text, "a build argument is baked into a layer"
    for forbidden in ("Get-Content", "ConvertFrom-StringData"):
        assert forbidden not in text, (
            f"{forbidden} could pull a value out of .env")


# -------------------------------------------------------- the shared contract


def test_the_exit_codes_match_the_python_side():
    """The script maps exit codes to statuses. Both sides must agree."""
    from backend.validation import live_verify as lv

    text = VERIFY.read_text(encoding="utf-8")
    for code, status in (
        (lv.EXIT_OK, "LIVE_VERIFIED"),
        (lv.EXIT_FAILED, "FAILED"),
        (lv.EXIT_PASSED_NOT_STORED, "PASSED_NOT_STORED"),
        (lv.EXIT_NOT_ELIGIBLE, "NOT_ELIGIBLE"),
    ):
        assert f"{code} {{ $Status = '{status}' }}" in text, (
            f"the script does not map exit {code} to {status}")


def test_every_mode_survived_the_rewrite():
    text = VERIFY.read_text(encoding="utf-8")
    for switch in ("DryRun", "Quick", "Critical", "FullRouting",
                   "FullCertification", "Yes", "Json"):
        assert f"[switch]${switch}" in text, f"-{switch} was lost"
    for mode in ("dryrun", "quick", "critical", "fullrouting",
                 "fullcertification"):
        assert f"'{mode}'" in text


def test_the_cost_table_matches_the_python_side():
    from backend.validation import live_verify as lv

    text = VERIFY.read_text(encoding="utf-8")
    for mode, calls in lv.ESTIMATED_CALLS.items():
        assert f"'{mode}'" in text
        assert f"= {calls}" in text, (
            f"the script does not quote {calls} calls for {mode}")
