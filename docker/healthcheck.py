#!/usr/bin/env python
"""
Is the IPM API answering?

Used as the container's health check. Written in Python rather than with curl so
the image needs no operating-system packages installed at build time — one less
thing that can fail on a machine behind a restrictive corporate proxy.

Exit 0 means healthy; anything else means not yet.
"""

from __future__ import annotations

import os
import sys
import urllib.request

URL = f"http://127.0.0.1:{os.environ.get('API_PORT', '8000')}/healthz"

try:
    with urllib.request.urlopen(URL, timeout=4) as response:  # noqa: S310 - fixed local URL
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
