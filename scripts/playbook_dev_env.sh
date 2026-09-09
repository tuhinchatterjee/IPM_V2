#!/usr/bin/env bash
#
# The isolated PostgreSQL cluster Playbook development runs against.
#
# Why this exists
# ---------------
# Git isolation is not database isolation. Playbook development writes real
# workspaces, sources and artifact versions, and seeds a demonstration on top of
# them, so it runs against its own cluster on its own port rather than sharing
# whatever happens to be listening on 5432.
#
# The cluster survives a container restart; the SERVER does not. Twice now that
# has cost time, because nothing in the repository said how to bring it back —
# and the port is the part that bites: this cluster's postgresql.conf carries no
# `port` line, so a bare `pg_ctl start` comes up on 5432 and every connection
# string in .env silently points at the wrong place. That is the whole reason
# this file is a script and not a sentence in a README.
#
#   scripts/playbook_dev_env.sh start     # idempotent; already-running is fine
#   scripts/playbook_dev_env.sh stop
#   scripts/playbook_dev_env.sh status
#   scripts/playbook_dev_env.sh create    # first time only; refuses to clobber
#
# It carries no credential. DATABASE_URL and SECRET_KEY live in the gitignored
# .env; this script names them and reads neither.
#
# Development only. It is not a deployment tool and knows nothing about one.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The port is the isolation guarantee, so it is written here rather than left to
# a default. Changing it means changing DATABASE_URL in .env to match.
PGPORT_DEV="${PLAYBOOK_PGPORT:-55432}"
PGDATA_DEV="${PLAYBOOK_PGDATA:-/var/lib/postgresql/playbook_dev}"
PGBIN="${PLAYBOOK_PGBIN:-/usr/lib/postgresql/16/bin}"
LOGDIR="$REPO/.playbook-dev/logs"
LOGFILE="$LOGDIR/postgres.log"

DB_DEV="creditprobe_playbook_dev"
DB_TEST="creditprobe_playbook_test"
DB_USER="ipm_app"

# The data directory belongs to `postgres` and this session is usually root, so
# every server command is run as that user. Running the server as root is
# refused by PostgreSQL itself, which is a good rule and not one to work around.
as_postgres() {
    if [ "$(id -un)" = "postgres" ]; then
        "$@"
    else
        su postgres -s /bin/bash -c "$(printf '%q ' "$@")"
    fi
}

running() {
    as_postgres "$PGBIN/pg_ctl" -D "$PGDATA_DEV" status >/dev/null 2>&1
}

require_cluster() {
    if [ ! -f "$PGDATA_DEV/PG_VERSION" ]; then
        echo "No cluster at $PGDATA_DEV."
        echo "Run: $0 create"
        exit 1
    fi
}

cmd_create() {
    # Refuses rather than reinitialising. An initdb over a populated directory
    # would destroy a seeded demonstration that takes minutes to rebuild, and
    # "it said it was already there" is a much better outcome than that.
    if [ -f "$PGDATA_DEV/PG_VERSION" ]; then
        echo "A cluster already exists at $PGDATA_DEV — leaving it alone."
        echo "To start it:  $0 start"
        exit 0
    fi
    mkdir -p "$PGDATA_DEV" "$LOGDIR"
    chown postgres:postgres "$PGDATA_DEV"
    # -U "$DB_USER": the bootstrap superuser IS the application user, which is
    # how the existing cluster was built. Letting initdb default to `postgres`
    # here would produce a cluster shaped differently from the one people
    # already have, and the difference would only surface as a confusing
    # "role does not exist" much later.
    as_postgres "$PGBIN/initdb" -D "$PGDATA_DEV" -U "$DB_USER" \
        --auth=trust --encoding=UTF8
    cmd_start
    for db in "$DB_DEV" "$DB_TEST"; do
        "$PGBIN/createdb" -p "$PGPORT_DEV" -h 127.0.0.1 -U "$DB_USER" \
            -O "$DB_USER" "$db"
    done
    echo
    echo "Created $DB_DEV and $DB_TEST on port $PGPORT_DEV."
    echo "Point .env at it (that file is gitignored and is not written here):"
    echo "  DATABASE_URL=postgresql+psycopg://$DB_USER@127.0.0.1:$PGPORT_DEV/$DB_DEV"
    echo "Then:  .venv/bin/python -m alembic upgrade head"
}

cmd_start() {
    require_cluster
    if running; then
        echo "Already running on port $PGPORT_DEV. Nothing to do."
        return 0
    fi
    mkdir -p "$LOGDIR"
    touch "$LOGFILE"
    chown postgres:postgres "$LOGFILE"
    # -o "-p PORT": this cluster's postgresql.conf sets no port, so leaving it
    # off starts it on 5432 and every connection string in .env is then quietly
    # wrong. It is passed here so that cannot happen.
    as_postgres "$PGBIN/pg_ctl" -D "$PGDATA_DEV" -l "$LOGFILE" \
        -o "-p $PGPORT_DEV" -w start
    cmd_status
}

cmd_stop() {
    require_cluster
    if ! running; then
        echo "Not running. Nothing to do."
        return 0
    fi
    as_postgres "$PGBIN/pg_ctl" -D "$PGDATA_DEV" -m fast -w stop
    echo "Stopped."
}

cmd_status() {
    if [ ! -f "$PGDATA_DEV/PG_VERSION" ]; then
        echo "cluster:   ABSENT at $PGDATA_DEV  (run: $0 create)"
        return 1
    fi
    if ! running; then
        echo "cluster:   present at $PGDATA_DEV"
        echo "server:    DOWN  (run: $0 start)"
        return 1
    fi
    echo "cluster:   present at $PGDATA_DEV"
    echo "server:    up on port $PGPORT_DEV"
    for db in "$DB_DEV" "$DB_TEST"; do
        # -U "$DB_USER" explicitly: the cluster's superuser is the application
        # user, so letting psql default to the OS user asks for a role that
        # does not exist and reports a present database as missing.
        if "$PGBIN/psql" -p "$PGPORT_DEV" -h 127.0.0.1 -U "$DB_USER" \
                -d "$db" -tAc "select 1" >/dev/null 2>&1; then
            echo "database:  $db  reachable"
        else
            echo "database:  $db  MISSING"
        fi
    done
    echo "log:       ${LOGFILE#"$REPO"/}"
}

case "${1:-status}" in
    create) cmd_create ;;
    start)  cmd_start ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    restart) cmd_stop; cmd_start ;;
    *)
        echo "usage: $0 {create|start|stop|restart|status}"
        exit 2
        ;;
esac
