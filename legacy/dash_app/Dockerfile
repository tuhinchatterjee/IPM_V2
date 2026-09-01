# syntax=docker/dockerfile:1.7
#
# IPM Tool — production image.
#
# Serves the Dash app with Waitress (serve.py) as a SINGLE process with 8 threads.
# This is a hard architectural constraint, not a tuning choice: the dataset lives
# in module-level globals in backend/data_loader.py plus a per-process cache, so
# the app must never be forked into multiple workers. Scale vertically (CPU/RAM
# on one container), never with replicas — two replicas would serve two
# independently-cached, divergent views of the portfolio.
#
# Build:  docker build -t ipm-tool:0.1.0 .
# Run:    see the header of .dockerignore and docs/deploy.md §9-10.

# ---------------------------------------------------------------- build stage
# Deps are compiled/installed into a throwaway venv here so the runtime image
# carries no compiler toolchain. Pin by digest (docker buildx imagetools inspect
# python:3.14-slim) once you have a release to freeze.
FROM python:3.14-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1

# build-essential covers any dependency without a cp314 wheel (argon2-cffi and
# cffi are the usual candidates on a new Python minor). It stays in this stage.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# requirements.txt is fully pinned (canonical source: pyproject.toml), so this
# layer is cached until a version actually changes.
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --requirement /tmp/requirements.txt

# -------------------------------------------------------------- runtime stage
FROM python:3.14-slim AS runtime

# No apt packages needed at runtime: pillow/matplotlib wheels vendor their own
# freetype/libjpeg/zlib and matplotlib ships the DejaVu fonts it renders report
# charts with, and psycopg[binary] vendors libpq.

# The whole dependency tree, already built — no compiler lands in this image.
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    # --- app configuration (backend/config.py). Everything here is a safe
    # default; secrets are injected at run time, never baked in. ---
    ENV=prod \
    HOST=0.0.0.0 \
    PORT=8050 \
    LOG_DIR=/app/logs \
    UPLOAD_DIR=/app/uploads \
    MAX_UPLOAD_MB=25 \
    # matplotlib writes a font cache on first import; without a writable dir it
    # warns and re-scans the font tree on every start.
    MPLCONFIGDIR=/var/cache/matplotlib

# Unprivileged, fixed uid/gid so bind-mounted logs/uploads have predictable
# ownership on the host.
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --no-create-home --home-dir /app app

WORKDIR /app

# Application code: root-owned and read-only to the app user, so a compromised
# request handler cannot rewrite the code it is running.
COPY --chown=root:root app.py serve.py alembic.ini ./
COPY --chown=root:root backend/ ./backend/
COPY --chown=root:root frontend/ ./frontend/
COPY --chown=root:root assets/ ./assets/
COPY --chown=root:root alembic/ ./alembic/
COPY --chown=root:root scripts/ ./scripts/

# Bundled workbooks. Portfolio_Monitoring_Dataset.xlsx is the fallback dataset
# served when Postgres holds no active version (and what scripts/migrate_xlsx_to_pg.py
# seeds); the other three back the Macro and RAROC screens. The raw IMF WEO export
# and the Oman climate workbook are deliberately excluded — no code path reads them.
COPY --chown=root:root Portfolio_Monitoring_Dataset.xlsx \
                       Macro_GCC_Compact.xlsx \
                       Post_Deal_RAROC_Sample.xlsx \
                       Post_Deal_RAROC2_Sample.xlsx \
                       ./

# The only writable paths. config.py mkdir()s LOG_DIR/UPLOAD_DIR at import, so
# they must be writable before the first import or the process dies on startup.
RUN mkdir -p /app/logs /app/uploads /var/cache/matplotlib \
 && chown -R app:app /app/logs /app/uploads /var/cache/matplotlib

USER app

# Prime matplotlib's font cache into the image. Cold, this scan is a large slice
# of the ~30s first-request latency; done here it is paid once at build time.
RUN python -c "import matplotlib; matplotlib.use('Agg'); from matplotlib import font_manager; font_manager.fontManager"

EXPOSE 8050

# /healthz is unauthenticated and reports DB reachability; it returns 503 (→
# unhealthy) when Postgres is unreachable. DATABASE_URL is not optional:
# backend/db/engine.py raises at import time when it is unset, so the container
# exits immediately rather than falling back to the bundled workbook.
# start-period covers dataset load + cache warm on a cold start.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import os,sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8050')+'/healthz',timeout=4).status==200 else 1)"]

STOPSIGNAL SIGTERM

# Waitress, not the Dash dev server. Run the container with --init so PID 1
# reaps children and forwards SIGTERM promptly.
CMD ["python", "serve.py"]
