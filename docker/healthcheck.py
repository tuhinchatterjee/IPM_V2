#!/usr/bin/env python
"""
Is CreditProbe ready to be demonstrated?

Used as the container's health check, and it asks TWO questions, because on a
fresh Mac the first one alone said yes to a product that was empty:

  1. Is the API answering?  `/healthz`
  2. Did the demonstration bootstrap pass its readiness checks?

The second is read from the marker the entrypoint writes. A container whose
corporate universe failed to build answers HTTP 200 on every route — the
screens load, they are simply empty — so an HTTP check calls it healthy and
`docker compose up` returns to the prompt looking successful. That is exactly
what happened, and it is why the readiness verdict is part of health rather
than something a presenter discovers in front of a client.

Written in Python rather than with curl so the image needs no operating-system
packages installed at build time — one less thing that can fail on a machine
behind a restrictive corporate proxy.

Exit 0 means healthy; anything else means not yet.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.request

PORT = os.environ.get("API_PORT", "8000")
URL = f"http://127.0.0.1:{PORT}/healthz"
MARKER = pathlib.Path(
    os.environ.get("CREDITPROBE_READY_MARKER", "/tmp/creditprobe-bootstrap.json"))


def api_answers() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=4) as response:  # noqa: S310 - fixed local URL
            return response.status == 200
    except Exception:
        return False


def demonstration_ready() -> tuple[bool, str]:
    """Whether the bootstrap wrote a passing verdict.

    A missing marker means the bootstrap has not finished yet, which during
    the first start is normal and is why compose gives this check a long
    `start_period`. It is NOT treated as ready: "we have not checked" and
    "we checked and it is fine" are different answers, and conflating them is
    the whole defect.
    """
    if not MARKER.exists():
        return False, "the demonstration bootstrap has not finished yet"
    try:
        body = json.loads(MARKER.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - an unreadable verdict is not a pass
        return False, f"the bootstrap verdict could not be read: {e}"
    if body.get("ok"):
        return True, ""
    return False, str(body.get("sentence") or "readiness checks did not pass")


def main() -> int:
    if not api_answers():
        print(f"CreditProbe API is not answering on {URL}", file=sys.stderr)
        return 1
    ready, why = demonstration_ready()
    if not ready:
        print(f"CreditProbe API is up but not demonstrable: {why}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
