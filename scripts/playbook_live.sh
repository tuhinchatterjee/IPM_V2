#!/usr/bin/env bash
#
# Start, stop and inspect the isolated Playbook instance.
#
#   scripts/playbook_live.sh start     # database, backend, frontend, then open it
#   scripts/playbook_live.sh stop      # only what this script started
#   scripts/playbook_live.sh status    # what is running, and whether it is ours
#   scripts/playbook_live.sh doctor    # configuration, without any secret
#
# This instance is deliberately separate from the main CreditProbe backend:
#
#   PostgreSQL  55432   isolated cluster, its own data directory
#   backend      8001   THIS Playbook API
#   frontend     3000
#
# The main IPM_V2 backend runs on 8000. Nothing here touches it.
#
# Two rules this script will not break:
#
#   * It stops only processes it started, identified by the PID files it wrote
#     AND by checking that the process is still the one it launched. It will
#     not offer to kill whatever owns a port. A port held by something else is
#     reported in words and the script stops.
#   * It never resets, checks out, stashes or reseeds anything. If the working
#     tree is dirty it says so and carries on starting; your uncommitted work
#     is yours.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/.playbook-dev/run"
LOGS="$ROOT/.playbook-dev/logs"

PG_PORT=55432
API_PORT=8001
WEB_PORT=3000

mkdir -p "$RUN" "$LOGS"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok      %s\n' "$*"; }
info() { printf '  ..      %s\n' "$*"; }
warn() { printf '  note    %s\n' "$*"; }
fail() { printf '  PROBLEM %s\n' "$*"; }

# --------------------------------------------------------------------------
# Ports and ownership
# --------------------------------------------------------------------------

port_pid() {          # port -> pid of whatever is listening, or nothing
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1
}

port_answers() {      # port -> 0 when something accepts a connection there
  # A second signal, because `lsof` can only see processes it is allowed to
  # see. In a container it reported port 3000 free while a server was happily
  # answering on it, and a launcher that concludes "free" from a tool that
  # cannot see is a launcher that starts a second copy.
  (exec 3<>/dev/tcp/127.0.0.1/"$1") 2>/dev/null && exec 3<&- && return 0
  return 1
}

port_busy() {         # port -> 0 when anything is there, named or not
  [ -n "$(port_pid "$1")" ] && return 0
  port_answers "$1"
}

port_owner() {        # port -> a human description of who holds it
  local pid; pid="$(port_pid "$1")"
  if [ -z "$pid" ]; then
    port_answers "$1" && { printf 'a process this account cannot see'; return; }
    printf 'nobody'; return
  fi
  printf '%s (pid %s)' "$(ps -p "$pid" -o comm= 2>/dev/null | tr -d ' ')" "$pid"
}

ours() {              # name -> 0 when our PID file names a live process
  local pid_file="$RUN/$1.pid"
  [ -f "$pid_file" ] || return 1
  local pid; pid="$(cat "$pid_file" 2>/dev/null)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

claim_port() {        # name port -> 0 when the port is free or already ours
  local name="$1" port="$2" pid held
  port_busy "$port" || return 0
  held="$(port_pid "$port")"
  pid="$(cat "$RUN/$name.pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && [ "$held" = "$pid" ]; then
    ok "$name is already running on $port"
    return 0
  fi
  fail "port $port is held by $(port_owner "$port"), which this script did not start."
  say  "        Nothing has been stopped. Decide what that process is before"
  say  "        going further — it may be a presentation, another worktree, or"
  say  "        the main CreditProbe backend."
  return 1
}

# --------------------------------------------------------------------------
# The pieces
# --------------------------------------------------------------------------

start_database() {
  if pg_isready -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1; then
    ok "PostgreSQL is answering on $PG_PORT"
    return 0
  fi
  info "starting the isolated cluster on $PG_PORT"
  if [ -x "$ROOT/scripts/playbook_dev_env.sh" ]; then
    "$ROOT/scripts/playbook_dev_env.sh" start >>"$LOGS/postgres.start.log" 2>&1
  fi
  if pg_isready -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1; then
    ok "PostgreSQL is up on $PG_PORT"
    return 0
  fi
  fail "the cluster on $PG_PORT did not come up. See $LOGS/postgres.start.log"
  say  "        On a Mac the data directory is wherever this worktree's"
  say  "        scripts/playbook_dev_env.sh points; it is not /var/lib."
  return 1
}

start_backend() {
  claim_port backend "$API_PORT" || return 1
  ours backend && return 0
  [ -f "$ROOT/.env" ] || { fail "no .env in $ROOT — the backend needs DATABASE_URL"; return 1; }

  info "starting the Playbook API on $API_PORT"
  # The port is substituted HERE, by this shell, before `.env` is sourced.
  #
  # Sourcing it inside the subshell used to clobber the variable: this
  # repository's .env sets API_PORT=8000 for the main CreditProbe backend, so
  # `set -a && . ./.env` overwrote 8001 and the launcher quietly started
  # Playbook on the other service's port — the one collision this script
  # exists to prevent. Baking the number into the command string closes that:
  # nothing .env contains can change it.
  # `set -m` gives this background job its own process group, so `stop` can
  # take down the whole tree. Without it `stop` kills the pid it recorded and
  # any grandchild survives — which is exactly what happened with the web
  # server: `next start` spawns `next-server`, the parent died, the child was
  # re-parented to init and kept port 3000, and the next `start` would have
  # found the port held by a stale build.
  set -m
  bash -c "cd '$ROOT' && set -a && . ./.env && set +a && \
    exec .venv/bin/python -m uvicorn backend.api.main:app \
      --host 127.0.0.1 --port $API_PORT" >>"$LOGS/backend.log" 2>&1 &
  echo $! > "$RUN/backend.pid"
  set +m

  for _ in $(seq 1 40); do
    curl -fsS -m 2 "http://127.0.0.1:$API_PORT/api/v1/playbook/capabilities" \
      >/dev/null 2>&1 && { ok "the API is answering on $API_PORT"; return 0; }
    sleep 1
  done
  fail "the API did not answer within 40s. See $LOGS/backend.log"
  return 1
}

start_frontend() {
  claim_port frontend "$WEB_PORT" || return 1
  ours frontend && return 0

  # The build decides which backend the browser calls, by TWO routes, and
  # both are fixed at build time:
  #
  #   NEXT_PUBLIC_API_URL    what the application's own client calls
  #   BACKEND_INTERNAL_URL   where next.config.ts rewrites same-origin
  #                          /api/... requests, which Next resolves during
  #                          `next build`, not at start
  #
  # Both default to 8000. Setting only the first leaves the rewrite pointing
  # at the main CreditProbe backend, so anything using the same-origin path —
  # a diagnostic, a curl against :3000, an acceptance script — silently reads
  # and writes the other service's data. That is the collision this script
  # exists to prevent, so both are set and both are stamped.
  # ORIGIN ONLY, no /api/v1. `src/lib/api.ts` holds the prefix itself —
  # `API_BASE_URL` is the origin and `API_PREFIX = "/api/v1"` is appended to
  # every path. Including it here produced /api/v1/api/v1/playbook/home, every
  # request 404'd, and the page rendered a shell with "Backend offline" and no
  # working composer. It looked like a broken product; it was a doubled path.
  local want="http://127.0.0.1:$API_PORT"
  local want_internal="http://127.0.0.1:$API_PORT"
  # The stamp carries BOTH addresses. A build made before the rewrite was
  # pointed at the Playbook API stamped only the first one, and would
  # otherwise be accepted as current while its /api proxy still went to 8000.
  local stamped="$want $want_internal"
  local stamp="$RUN/frontend-api-url"
  local have=""
  [ -f "$stamp" ] && have="$(cat "$stamp" 2>/dev/null)"

  # A build can also be out of date because the SOURCE moved. That is not a
  # theoretical case: an interface change was made, `start` saw a matching
  # address stamp, served the previous bundle, and the browser suite then
  # failed on text that was sitting in the working tree. A stale build is
  # worse than a slow start, because it looks like a product defect.
  local stale_source=""
  if [ -d "$ROOT/frontend/.next" ]; then
    stale_source="$(find "$ROOT/frontend/src" "$ROOT/frontend/next.config.ts" \
      "$ROOT/frontend/package.json" -newer "$ROOT/frontend/.next/BUILD_ID" \
      -type f -print -quit 2>/dev/null || true)"
  fi

  if [ ! -d "$ROOT/frontend/.next" ] || [ "$have" != "$stamped" ] \
     || [ -n "$stale_source" ]; then
    if [ -n "$stale_source" ] && [ "$have" = "$stamped" ]; then
      info "the build is older than the source; rebuilding"
      info "(first file newer than the build: ${stale_source#"$ROOT"/})"
    elif [ -d "$ROOT/frontend/.next" ]; then
      info "the existing build points at ${have:-an unrecorded backend};"
      info "rebuilding for $stamped"
    else
      info "no build yet; building the frontend for $want"
    fi
    ( cd "$ROOT/frontend" && NEXT_PUBLIC_API_URL="$want" \
        BACKEND_INTERNAL_URL="$want_internal" npm run build ) \
      >>"$LOGS/frontend-build.log" 2>&1 || {
        fail "the frontend build failed. See $LOGS/frontend-build.log"
        return 1
      }
    printf '%s' "$stamped" > "$stamp"
    ok "built the frontend against $want"
  else
    ok "the existing build already points at $want"
  fi

  info "starting the web server on $WEB_PORT"
  set -m
  bash -c "cd '$ROOT/frontend' && BACKEND_INTERNAL_URL='$want_internal' \
    exec npx next start --port $WEB_PORT" \
    >>"$LOGS/frontend.log" 2>&1 &
  echo $! > "$RUN/frontend.pid"
  set +m

  for _ in $(seq 1 40); do
    curl -fsS -m 2 "http://127.0.0.1:$WEB_PORT/playbook" >/dev/null 2>&1 \
      && { ok "Playbook is on http://127.0.0.1:$WEB_PORT/playbook"; return 0; }
    sleep 1
  done
  fail "the web server did not answer within 40s. See $LOGS/frontend.log"
  return 1
}

stop_one() {
  local name="$1" pid
  pid="$(cat "$RUN/$name.pid" 2>/dev/null || true)"
  if [ -z "$pid" ]; then info "$name was not started by this script"; return 0; fi
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$RUN/$name.pid"; info "$name had already stopped"; return 0
  fi
  # The group first, then the pid, because a service may have children that
  # outlive it. A negative argument to kill means "this process group", and
  # the group exists because `start` launched the job under `set -m`. The
  # plain pid stays as the fallback for a pid file written before that.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
  for _ in $(seq 1 15); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
  fi
  rm -f "$RUN/$name.pid"
  ok "stopped $name (pid $pid)"
}

# --------------------------------------------------------------------------

cmd_start() {
  say "Playbook — starting the isolated instance in $ROOT"
  if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    warn "the working tree has uncommitted changes. Nothing here will touch them."
  fi
  start_database || return 1
  start_backend  || return 1
  start_frontend || return 1
  say ""
  say "Open:  http://127.0.0.1:$WEB_PORT/playbook"
  say "Stop:  scripts/playbook_live.sh stop"
  command -v open >/dev/null 2>&1 && open "http://127.0.0.1:$WEB_PORT/playbook"
  return 0
}

cmd_stop() {
  say "Playbook — stopping only what this script started"
  stop_one frontend
  stop_one backend

  # Checked, not assumed. "stopped" that leaves the port held is the failure
  # this check exists to catch, and it caught a real one.
  sleep 1
  for pair in "backend $API_PORT" "frontend $WEB_PORT"; do
    set -- $pair
    port_busy "$2" && warn "$2 is still held by $(port_owner "$2") — $1 left \
something behind, or another process took the port"
  done

  info "the PostgreSQL cluster is left running; stop it with"
  info "scripts/playbook_dev_env.sh stop"
}

cmd_status() {
  say "Playbook — status"
  pg_isready -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1 \
    && ok "PostgreSQL $PG_PORT answering" || fail "PostgreSQL $PG_PORT silent"
  for pair in "backend $API_PORT" "frontend $WEB_PORT"; do
    set -- $pair
    if ours "$1"; then ok "$1 $2 running, started by this script"
    elif port_busy "$2"; then
      warn "$1 port $2 held by $(port_owner "$2") — not ours"
    else info "$1 $2 not running"; fi
  done
  say ""
  say "Main CreditProbe backend (port 8000) is a different service:"
  port_busy 8000 && info "8000 held by $(port_owner 8000)" \
                || info "8000 not in use"
}

cmd_doctor() {
  say "Playbook — configuration. No secret is printed."
  say ""
  printf '  worktree      %s\n' "$ROOT"
  printf '  branch        %s\n' "$(git -C "$ROOT" branch --show-current 2>/dev/null)"
  printf '  commit        %s\n' "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null)"
  printf '  python        %s\n' "$([ -x "$ROOT/.venv/bin/python" ] && "$ROOT/.venv/bin/python" -V 2>&1 || echo 'no .venv')"
  printf '  frontend      %s\n' "$([ -d "$ROOT/frontend/.next" ] && echo 'built' || echo 'NOT BUILT')"
  printf '  build points  %s\n' "$(cat "$RUN/frontend-api-url" 2>/dev/null || echo 'not recorded — start will rebuild')"
  printf '  .env          %s\n' "$([ -f "$ROOT/.env" ] && echo 'present' || echo 'MISSING')"
  for key in DATABASE_URL ANTHROPIC_API_KEY AI_AUTHOR_MODEL NEXT_PUBLIC_API_URL; do
    if [ -f "$ROOT/.env" ] && grep -q "^${key}=." "$ROOT/.env" 2>/dev/null; then
      printf '  %-13s set\n' "$key"
    else
      printf '  %-13s not set\n' "$key"
    fi
  done
  say ""
  say "  Values are never shown — only whether each is present. Without"
  say "  ANTHROPIC_API_KEY the workspaces, files and status stay browseable"
  say "  and generation reports itself unavailable."
  say ""
  if curl -fsS -m 3 "http://127.0.0.1:$API_PORT/api/v1/playbook/capabilities" 2>/dev/null \
      | grep -q '"scripted": *true'; then
    warn "this backend is answering from a SCRIPTED assistant (fixture content)."
  fi
  say "  Migration head:"
  ( cd "$ROOT" && set -a && . ./.env 2>/dev/null && set +a \
      && .venv/bin/alembic current 2>/dev/null | tail -1 ) || true
}

case "${1:-status}" in
  start)  cmd_start  ;;
  stop)   cmd_stop   ;;
  status) cmd_status ;;
  doctor) cmd_doctor ;;
  *) say "usage: scripts/playbook_live.sh {start|stop|status|doctor}"; exit 2 ;;
esac
