"""The one switch for the Guided Risk Workspace surface.

OFF (the default): `app.create_app` does not include the workspace router, the
LLM exchange recorder is governed by its own flag, and the accepted Cockpit is
unchanged. ON: the workspace routes are served under
`/api/v1/cockpit-v4/workspace/` -- a V4-served prefix, so the frontend's
runtime guard lets the calls through.
"""

from __future__ import annotations

import os

FLAG = "COCKPIT_V4_GUIDED_WORKSPACE"
_TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in _TRUE


__all__ = ["FLAG", "enabled"]
