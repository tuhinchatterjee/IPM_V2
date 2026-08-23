# =============================================================================
# IPM backend — FastAPI, the analytical engine, DuckDB and the Data Access Layer
# =============================================================================
#
# Build from the REPOSITORY ROOT (docker-compose.yml does this for you):
#
#     docker build -f docker/backend.Dockerfile -t ipm-backend .
#
# The image contains Python and every dependency IPM needs, so nothing has to be
# installed on the host machine.
#
# Deliberately no `apt-get` step. Everything the container needs at run time —
# waiting for the database, the health check — is done with Python, which is
# already here. That removes a whole class of build failure on machines behind a
# corporate proxy that does not allow the Debian package mirrors.
#
# The analytical data (data/) and the governed catalogue (metadata/) are NOT
# baked in — they are mounted from the repository at run time. That keeps the
# image small, means a rebuild is not needed when data changes, and lets the
# Parquet layer the container generates on first start persist on the host.

# Parameterised so a machine behind a TLS-inspecting corporate proxy can point
# the build at a base image that already trusts its certificate authority.
# Leave it alone and the standard public image is used.
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

# - PYTHONDONTWRITEBYTECODE: no .pyc litter in a mounted volume
# - PYTHONUNBUFFERED: logs appear in `docker compose logs` immediately rather
#   than being held in a buffer, which matters when something goes wrong
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, and only the file that describes them: Docker caches this
# layer, so editing application code rebuilds in seconds instead of minutes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Now the application itself.
COPY alembic.ini pyproject.toml ./
COPY alembic/ ./alembic/
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY data/raw/ ./data/raw/

COPY docker/backend-entrypoint.sh /usr/local/bin/ipm-entrypoint
COPY docker/healthcheck.py /usr/local/bin/ipm-healthcheck.py

# Strip carriage returns and set the executable bit, rather than trusting how
# the repository happened to be checked out.
#
# .gitattributes pins these files to LF, but a clone made before that existed —
# or copied onto the machine some other way — can still carry Windows CRLF line
# endings. A shell script with CRLF fails immediately inside a Linux container:
# the kernel reads the shebang as `#!/usr/bin/env bash\r` and reports
# `env: 'bash\r': No such file or directory`. Two lines here make the image
# build correctly from any checkout on any operating system.
RUN sed -i 's/\r$//' /usr/local/bin/ipm-entrypoint /usr/local/bin/ipm-healthcheck.py \
 && chmod 0755 /usr/local/bin/ipm-entrypoint

# Inside the container the API must listen on every interface, not just
# loopback: 127.0.0.1 inside a container is the container itself, and Docker
# could not forward port 8000 to it.
ENV API_HOST=0.0.0.0 \
    API_PORT=8000 \
    ENV=dev

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=30 \
  CMD ["python", "/usr/local/bin/ipm-healthcheck.py"]

ENTRYPOINT ["ipm-entrypoint"]
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
