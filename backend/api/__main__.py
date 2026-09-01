"""
Development entry point:  python -m backend.api

Runs the API with auto-reload so a code change is picked up without a restart.
Production uses a process manager pointed at `backend.api.main:app` instead.
"""

import uvicorn

from backend.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "backend.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=not settings.is_prod,
        log_level="info",
    )
