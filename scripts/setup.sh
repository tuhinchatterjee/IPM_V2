#!/usr/bin/env bash
#
# One-time setup. Run this once after downloading CreditProbe:
#
#     ./scripts/setup.sh
#
# It installs everything CreditProbe needs. After it finishes, start CreditProbe with:
#
#     ./scripts/dev.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
step() { echo; echo "${BOLD}▸ $*${RESET}"; }
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}!${RESET} $*"; }
die()  { echo; echo "  ${RED}✗${RESET} $1" >&2; [ $# -gt 1 ] && echo "    $2"; echo; exit 1; }

echo "${BOLD}CreditProbe — first-time setup${RESET}"

# ------------------------------------------------------------------- python

step "Setting up Python"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "Python is not installed." "Install Python 3.11+ from https://www.python.org/downloads/"

VERSION="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python $VERSION is too old. CreditProbe needs 3.11 or newer." "Install a newer Python from https://www.python.org/downloads/"
ok "Python $VERSION"

if [ ! -d .venv ]; then
  # A virtual environment keeps CreditProbe's packages separate from everything else on
  # the machine, so installing CreditProbe can never break another Python project.
  "$PY" -m venv .venv
  ok "Created the .venv folder"
else
  ok ".venv already exists"
fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY=".venv/Scripts/python.exe"

"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r requirements.txt
ok "Python packages installed"

# ----------------------------------------------------------------- frontend

step "Setting up the frontend"
command -v npm >/dev/null 2>&1 || die "Node.js is not installed." "Install Node.js 20+ from https://nodejs.org/"
ok "Node.js $(node -v)"
(cd frontend && npm install --silent)
ok "Frontend packages installed"

# ---------------------------------------------------------------------- env

step "Setting up configuration"
if [ -f .env ]; then
  ok ".env already exists — leaving it alone"
else
  cp .env.example .env
  # Generate a real signing key so the user does not have to.
  KEY="$("$VENV_PY" -c 'import secrets; print(secrets.token_hex(32))')"
  # A sed that behaves the same on macOS and Linux.
  "$VENV_PY" - "$KEY" <<'PYEOF'
import pathlib, sys
key = sys.argv[1]
p = pathlib.Path(".env")
p.write_text(p.read_text().replace("SECRET_KEY=", f"SECRET_KEY={key}", 1))
PYEOF
  ok "Created .env with a generated SECRET_KEY"
  warn "Open .env and change POSTGRES_PASSWORD (and the password inside DATABASE_URL to match)."
fi

# ---------------------------------------------------------------- data lake

step "Building the analytical data"
"$VENV_PY" scripts/generate_saudi_universe.py

# ------------------------------------------------------------------- docker

step "Checking Docker"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "Docker is running — the database will start automatically"
else
  warn "Docker is not running. Install/start Docker Desktop before running ./scripts/dev.sh"
  warn "https://www.docker.com/products/docker-desktop/"
fi

cat <<DONE

${GREEN}${BOLD}  Setup complete.${RESET}

    ${BOLD}1.${RESET} Open ${BOLD}.env${RESET} and set ${BOLD}POSTGRES_PASSWORD${RESET} to a password of your choice.
       Change the password inside ${BOLD}DATABASE_URL${RESET} on the next line to match.

    ${BOLD}2.${RESET} Start CreditProbe:   ${BOLD}./scripts/dev.sh${RESET}

    ${BOLD}3.${RESET} Open:        ${BOLD}http://localhost:3000${RESET}

DONE
