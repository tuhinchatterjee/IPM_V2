#!/usr/bin/env python3
"""
Parse a PowerShell script, and refuse the ones Windows will refuse.

Why this exists
---------------
`scripts/verify-live-ai.ps1` shipped in a state that could not be parsed on
Windows PowerShell 5.1 at all:

    The string is missing the terminator: ".

The cause was not visible at the line the parser named. The file was UTF-8
without a byte order mark, and Windows PowerShell 5.1 reads such a file using
the system ANSI code page rather than UTF-8. On a Western install that is
CP1252, so the three UTF-8 bytes of an em dash (E2 80 94) decode as

    U+00E2  LATIN SMALL LETTER A WITH CIRCUMFLEX
    U+20AC  EURO SIGN
    U+201D  RIGHT DOUBLE QUOTATION MARK

and PowerShell's tokenizer accepts U+201D as a closing double quote. One em
dash inside a double-quoted string therefore ended that string early, the real
closing quote opened a new one, and the parser ran hundreds of lines further
before giving up. Every Linux tool in the repository read the file perfectly.

So "it opens fine here" proves nothing, and neither does eyeballing the line
the error names. This module does two things instead.

**If a PowerShell runtime is available** it asks PowerShell's own parser, which
is the only authority that matters.

**When one is not** — and there is none in CI here — it runs a source-level
check that would have caught this specific failure and the family it belongs
to: a hand-written tokenizer that follows PowerShell's own string rules and
reports an unterminated string, plus byte-level and syntax-level rules for the
things that differ between Windows PowerShell 5.1 and PowerShell 7.

The source-level check is not a substitute for the real parser and does not
claim to be. It is a floor.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Quotation marks PowerShell accepts as string delimiters besides the ASCII
#: ones. Convenient when a script is pasted out of a word processor, and fatal
#: when one appears by accident through a code-page mismatch.
#:
#: The tokenizer below honours them for the same reason PowerShell does: a
#: model that treated them as ordinary characters would report a file as
#: parsing cleanly when Windows will not parse it at all, which is the precise
#: mistake this whole module exists to stop being made twice.
SMART_QUOTES = {
    "‘": "left single quotation mark",
    "’": "right single quotation mark",
    "‚": "single low-9 quotation mark",
    "‛": "single high-reversed-9 quotation mark",
    "“": "left double quotation mark",
    "”": "right double quotation mark",
    "„": "double low-9 quotation mark",
    "″": "double prime",
}

#: Which ASCII quote each one stands in for, when it is acting as a delimiter.
SMART_SINGLE = frozenset({"\u2018", "\u2019", "\u201a", "\u201b"})
SMART_DOUBLE = frozenset({"\u201c", "\u201d", "\u201e", "\u2033"})

#: Syntax that exists only in PowerShell 7 and is a parse error on 5.1.
#:
#: Each entry is (pattern, what it is). Applied to code only — never to
#: comments or string bodies, because a script is allowed to describe syntax it
#: does not use.
PS7_ONLY: tuple[tuple[str, str], ...] = (
    (r"\?\?=", "null-coalescing assignment (??=), PowerShell 7 only"),
    (r"\?\?", "null-coalescing operator (??), PowerShell 7 only"),
    (r"\$\w+\?\.", "null-conditional member access (?.), PowerShell 7 only"),
    (r"\$\w+\?\[", "null-conditional index (?[), PowerShell 7 only"),
    (r"(?<![|&\d\w])&&(?![&])", "pipeline chain operator (&&), PowerShell 7 only"),
    (r"(?<![|&\d\w])\|\|(?![|])", "pipeline chain operator (||), PowerShell 7 only"),
    (r"-Parallel\b", "ForEach-Object -Parallel, PowerShell 7 only"),
    (r"\bGet-Error\b", "Get-Error, PowerShell 7 only"),
    (r"-ErrorAction\s+Break\b", "ErrorAction Break, PowerShell 7 only"),
    (r"\bConvertFrom-Json\s+[^|\r\n]*-AsHashtable\b",
     "ConvertFrom-Json -AsHashtable, PowerShell 7 only"),
    (r"\bTest-Json\b", "Test-Json, PowerShell 7 only"),
    (r"\bJoin-String\b", "Join-String, PowerShell 7 only"),
)

#: Anything that looks like a credential, in a file that is committed.
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"sk-ant[-\w]*", "an Anthropic API key"),
    (r"sk_live[-\w]*", "a live secret key"),
    (r"sk-proj[-\w]*", "a project API key"),
    (r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}", "a bearer credential"),
    (r"(?i)ANTHROPIC_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{8,}",
     "an assignment of ANTHROPIC_API_KEY to a value"),
)


@dataclass(frozen=True)
class Problem:
    """One reason a script must not ship."""

    kind: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.kind} (line {self.line}): {self.detail}"


# ---------------------------------------------------------------------------
# The tokenizer
# ---------------------------------------------------------------------------


class Unterminated(Exception):
    """A string, comment or here-string that never closed."""

    def __init__(self, kind: str, line: int) -> None:
        super().__init__(f"unterminated {kind} opened at line {line}")
        self.kind = kind
        self.line = line


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def spans(text: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Split a script into (code spans, non-code spans).

    Non-code is comments and the BODIES of string literals. Everything else is
    code. The split is what makes the syntax and secret rules honest: a script
    is allowed to *describe* PowerShell 7 syntax in its help text, and it must
    not *use* it.

    Follows PowerShell's own rules:

      * `'...'` takes no escapes; `''` is a literal quote.
      * `"..."` uses a backtick to escape, `""` for a literal quote, and may
        contain `$( ... )` subexpressions holding arbitrary code.
      * `@'` / `'@` and `@"` / `"@` here-strings close only at line start.
      * `#` runs to end of line; `<# ... #>` blocks do not nest.

    Raises `Unterminated` when something never closes, which is exactly the
    failure that shipped.
    """
    code: list[tuple[int, int]] = []
    other: list[tuple[int, int]] = []

    i = 0
    n = len(text)
    code_start = 0
    # Depth of $( ) subexpressions we are inside, with the quote that opened
    # the string each one interrupts.
    interrupted: list[str] = []

    def close_code(end: int) -> None:
        if end > code_start:
            code.append((code_start, end))

    while i < n:
        ch = text[i]
        following = text[i + 1] if i + 1 < n else ""

        # --- here-strings, checked before the plain quotes they start with ---
        if ch == "@" and following in ('"', "'"):
            rest = text[i + 2:i + 3]
            if rest in ("\r", "\n", ""):
                quote = following
                opened = _line_of(text, i)
                close_code(i)
                terminator = re.compile(
                    r"^" + re.escape(quote) + r"@", re.M)
                found = terminator.search(text, i + 2)
                if found is None:
                    raise Unterminated(f"here-string ({quote}@)", opened)
                end = found.end()
                other.append((i, end))
                i = end
                code_start = i
                continue

        # --- block comment -------------------------------------------------
        if ch == "<" and following == "#":
            opened = _line_of(text, i)
            close_code(i)
            end = text.find("#>", i + 2)
            if end == -1:
                raise Unterminated("block comment (<#)", opened)
            end += 2
            other.append((i, end))
            i = end
            code_start = i
            continue

        # --- line comment --------------------------------------------------
        if ch == "#":
            close_code(i)
            end = text.find("\n", i)
            end = n if end == -1 else end
            other.append((i, end))
            i = end
            code_start = i
            continue

        # --- single-quoted string ------------------------------------------
        if ch == "'" or ch in SMART_SINGLE:
            opened = _line_of(text, i)
            close_code(i)
            closers = {"'"} | SMART_SINGLE
            j = i + 1
            while True:
                while j < n and text[j] not in closers:
                    j += 1
                if j >= n:
                    raise Unterminated("single-quoted string", opened)
                if text[j + 1:j + 2] in closers:
                    j += 2
                    continue
                break
            other.append((i, j + 1))
            i = j + 1
            code_start = i
            continue

        # --- double-quoted string, with subexpressions ----------------------
        if ch == '"' or ch in SMART_DOUBLE:
            opened = _line_of(text, i)
            close_code(i)
            closers = {'"'} | SMART_DOUBLE
            j = i + 1
            body_start = j
            while True:
                if j >= n:
                    raise Unterminated("double-quoted string", opened)
                c = text[j]
                if c == "`":
                    j += 2
                    continue
                if c in closers:
                    if text[j + 1:j + 2] in closers:
                        j += 2
                        continue
                    break
                if c == "$" and text[j + 1:j + 2] == "(":
                    # The body so far is not code; what follows the $( is.
                    other.append((body_start, j))
                    interrupted.append('"')
                    i = j + 2
                    code_start = i
                    break
                j += 1
            else:  # pragma: no cover - the while has no natural exit
                raise Unterminated("double-quoted string", opened)

            if interrupted:
                # Inside a subexpression now; the outer string resumes when it
                # closes, which the ")" branch below handles.
                continue
            other.append((body_start, j))
            i = j + 1
            code_start = i
            continue

        # --- the close of a subexpression inside a string -------------------
        if ch == ")" and interrupted:
            quote = interrupted.pop()
            closers = ({'"'} | SMART_DOUBLE) if quote == '"' else {"'"} | SMART_SINGLE
            close_code(i)
            # Resume scanning the interrupted string body.
            j = i + 1
            body_start = j
            opened = _line_of(text, i)
            while True:
                if j >= n:
                    raise Unterminated("double-quoted string", opened)
                c = text[j]
                if c == "`":
                    j += 2
                    continue
                if c in closers:
                    if text[j + 1:j + 2] in closers:
                        j += 2
                        continue
                    break
                if c == "$" and text[j + 1:j + 2] == "(":
                    other.append((body_start, j))
                    interrupted.append(quote)
                    i = j + 2
                    code_start = i
                    break
                j += 1
            if interrupted:
                continue
            other.append((body_start, j))
            i = j + 1
            code_start = i
            continue

        i += 1

    if interrupted:
        raise Unterminated("subexpression inside a string", _line_of(text, n))
    close_code(n)
    return code, other


def code_only(text: str) -> str:
    """The script with comments and string bodies blanked out.

    Blanked rather than removed, so every reported line number still matches
    the file a person will open.
    """
    _, blanked = spans(text)
    out = list(text)
    for start, end in blanked:
        for index in range(start, end):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def check_bytes(raw: bytes) -> list[Problem]:
    """What Windows will make of these bytes before it parses anything."""
    found: list[Problem] = []

    if raw.startswith(b"\xef\xbb\xbf"):
        # Not fatal, but this file is ASCII by policy and a BOM would mean
        # somebody re-saved it from an editor that changed the encoding.
        found.append(Problem(
            "encoding", 1,
            "the file starts with a UTF-8 byte order mark; this script is "
            "kept pure ASCII so that no code page can misread it"))

    for index, byte in enumerate(raw):
        if byte > 0x7F:
            line = raw.count(b"\n", 0, index) + 1
            try:
                shown = raw.decode("utf-8")[
                    max(0, len(raw[:index].decode("utf-8", "replace")) - 30):][:60]
            except Exception:  # noqa: BLE001 - the report must not depend on it
                shown = ""
            found.append(Problem(
                "encoding", line,
                f"byte 0x{byte:02X} is outside ASCII. Windows PowerShell 5.1 "
                "reads a BOM-less .ps1 as the system ANSI code page, so a "
                "multi-byte UTF-8 character can decode into a smart quote and "
                "silently open a string. Use ASCII. "
                + (f"Near: {shown.strip()!r}" if shown else "")))
            break  # One report is enough; they all have the same cause.

    return found


#: Scripts held to the full policy, not merely to "it parses".
#:
#: Every .ps1 in the repository must tokenize, be ASCII, carry no smart quote
#: and use no PowerShell 7 syntax — those are correctness. Declaring a
#: supported version and pinning StrictMode is a standard this phase set for
#: the verification tool; imposing it retroactively on older helpers would be
#: scope creep dressed up as rigour.
STRICT: frozenset[str] = frozenset({"verify-live-ai.ps1"})


def check_source(text: str, path: Path, strict: bool | None = None) -> list[Problem]:
    """Everything that can be said without a PowerShell runtime."""
    if strict is None:
        strict = path.name in STRICT
    found: list[Problem] = []

    # --- does it tokenize at all? -----------------------------------------
    try:
        code = code_only(text)
    except Unterminated as e:
        return [Problem("parse", e.line, str(e))]

    # --- smart quotes, anywhere -------------------------------------------
    for index, ch in enumerate(text):
        if ch in SMART_QUOTES:
            found.append(Problem(
                "smart-quote", _line_of(text, index),
                f"{SMART_QUOTES[ch]} (U+{ord(ch):04X}). PowerShell accepts "
                "this as a string delimiter, so it changes how the file "
                "parses."))

    # --- PowerShell 7 only syntax, in code ---------------------------------
    for pattern, what in PS7_ONLY:
        for match in re.finditer(pattern, code):
            found.append(Problem(
                "ps51-incompatible", _line_of(text, match.start()),
                f"{what}: {match.group(0)!r}"))

    # --- secrets, anywhere -------------------------------------------------
    for pattern, what in SECRET_PATTERNS:
        for match in re.finditer(pattern, text):
            found.append(Problem(
                "secret", _line_of(text, match.start()),
                f"this looks like {what} and must never be committed"))

    # --- balance, in code --------------------------------------------------
    for opener, closer, name in (("{", "}", "brace"), ("(", ")", "parenthesis"),
                                 ("[", "]", "bracket")):
        depth = 0
        for index, ch in enumerate(code):
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth < 0:
                    found.append(Problem(
                        "parse", _line_of(text, index),
                        f"a closing {name} with nothing open"))
                    break
        if depth > 0:
            found.append(Problem("parse", text.count("\n") + 1,
                                 f"{depth} {name}(s) never closed"))

    # --- the version this file promises to run on --------------------------
    if strict and not re.search(r"^#Requires\s+-Version\s+5\.1\s*$", text, re.M):
        found.append(Problem(
            "policy", 1,
            "no '#Requires -Version 5.1' line, so Windows PowerShell 5.1 is "
            "not declared as supported"))

    if "Set-StrictMode -Version Latest" in code:
        found.append(Problem(
            "ps51-incompatible", _line_of(text, code.index(
                "Set-StrictMode -Version Latest")),
            "Set-StrictMode -Version Latest means different things on 5.1 and "
            "7. Pin a number."))

    if strict and not text.endswith("\n"):
        found.append(Problem("policy", text.count("\n") + 1,
                             "the file does not end with a newline"))

    return found


# ---------------------------------------------------------------------------
# The real parser, when there is one
# ---------------------------------------------------------------------------


def powershell() -> str:
    """The PowerShell executable on this machine, or an empty string."""
    from shutil import which

    for candidate in ("pwsh", "powershell"):
        found = which(candidate)
        if found:
            return found
    return ""


def check_with_powershell(path: Path, executable: str = "") -> list[Problem]:
    """Ask PowerShell's own parser. The only authority that matters.

    Returns an empty list when there is no runtime to ask — the CALLER decides
    what that means, because "nothing was found" and "nothing could look" are
    different and must never be reported as the same thing. Use
    `powershell()` to tell them apart.
    """
    exe = executable or powershell()
    if not exe:
        return []

    script = (
        "$ErrorActionPreference='Stop';"
        "$tokens=$null;$errors=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{path.as_posix()}',[ref]$tokens,[ref]$errors);"
        "if($errors){foreach($e in $errors){"
        "Write-Output ('{0}|{1}' -f $e.Extent.StartLineNumber,$e.Message)}}"
    )
    try:
        completed = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120, check=False)
    except Exception as e:  # noqa: BLE001 - an absent runtime is not a failure
        return [Problem("parse", 1, f"the PowerShell parser could not run: {e}")]

    out: list[Problem] = []
    for line in (completed.stdout or "").splitlines():
        if "|" not in line:
            continue
        where, _, message = line.partition("|")
        try:
            number = int(where.strip())
        except ValueError:
            number = 1
        out.append(Problem("parse", number, message.strip()))
    return out


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def check(path: Path, strict: bool | None = None) -> list[Problem]:
    """Every problem with one script, byte level upward."""
    raw = path.read_bytes()
    found = check_bytes(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return [*found, Problem("encoding", 1, f"not valid UTF-8: {e}")]

    found.extend(check_source(text, path, strict))
    found.extend(check_with_powershell(path))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_powershell",
        description="Refuse a PowerShell script Windows would refuse.")
    parser.add_argument("paths", nargs="*",
                        help="Scripts to check. Default: scripts/*.ps1")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    paths = ([Path(p) for p in args.paths]
             or sorted((root / "scripts").glob("*.ps1")))
    if not paths:
        print("No PowerShell scripts to check.")
        return 0

    exe = powershell()
    print(f"PowerShell runtime: {exe or 'NOT AVAILABLE (source checks only)'}")

    total = 0
    for path in paths:
        problems = check(path)
        total += len(problems)
        mark = "FAIL" if problems else "ok"
        print(f"{mark:>4}  {path}")
        for problem in problems:
            print(f"        {problem}")
    return 1 if total else 0


if __name__ == "__main__":  # pragma: no cover - the entry point
    raise SystemExit(main())
