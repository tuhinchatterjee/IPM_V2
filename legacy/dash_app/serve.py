"""
Production entrypoint — serves the Dash app with Waitress (a pure-Python WSGI
server that runs well on Windows, unlike gunicorn).

Run directly (`python serve.py`) or via the NSSM Windows service (see
docs/deploy.md). The dev server in app.py's __main__ block is for local
development only.

IMPORTANT: single process, multiple threads. The dataset lives in module-level
globals in data_loader.py (and, from Phase 2, a per-process cache), so the app
must not be forked into multiple worker processes.
"""

import logging

from waitress import serve

import app as app_module  # importing app.py initializes logging + builds the app
from backend.config import settings

logger = logging.getLogger(__name__)

# Allow generous headroom over the configured upload cap: dcc.Upload base64-encodes
# the file inside a JSON callback body (~1.37x), and the real byte-limit is enforced
# in the upload callback itself.
_MAX_BODY_BYTES = settings.max_upload_bytes * 2


def main() -> None:
    logger.info(
        "Starting IPM Tool (Waitress) on %s:%s — env=%s, threads=8",
        settings.host, settings.port, settings.env,
    )
    serve(
        app_module.server,
        host=settings.host,
        port=settings.port,
        threads=8,
        channel_timeout=120,
        max_request_body_size=_MAX_BODY_BYTES,
        ident="IPM-Tool",
    )


if __name__ == "__main__":
    main()
