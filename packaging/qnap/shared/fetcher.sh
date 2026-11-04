#!/bin/bash
# Fetcher QPKG service program: brings the Docker Compose stack up and down.
# Invoked by QTS as `fetcher.sh start | stop | restart | status` (as admin).

set -u

QPKG_NAME="fetcher"

# ---------------------------------------------------------------- helpers

# Resolve the QPKG install dir (e.g. /share/CACHEDEV1_DATA/.qpkg/fetcher).
# The service script itself runs from /etc/init.d/, so we can't rely on $0.
function get_install_dir() {
    local dir
    dir=$(sed -n "/^\[${QPKG_NAME}\]/,/^\[/p" /etc/config/qpkg.conf \
        | grep "^InstallPath" | head -n1 | cut -d= -f2 | tr -d '"' | tr -d ' ')
    if [ -z "$dir" ] || [ ! -d "$dir" ]; then
        return 1
    fi
    echo "$dir"
}

# Find a working docker CLI and a compose command on QTS.
# Container Station ships docker at /usr/local/bin/docker.
function get_compose() {
    local docker_bin=""
    for b in $(which docker 2>/dev/null) /usr/local/bin/docker /usr/bin/docker; do
        if [ -x "$b" ]; then docker_bin="$b"; break; fi
    done
    if [ -z "$docker_bin" ]; then
        echo "docker CLI not found - is Container Station (or sshd+docker) installed?" >&2
        return 1
    fi
    if "$docker_bin" compose version >/dev/null 2>&1; then
        echo "$docker_bin compose"
    else
        echo "$docker_bin-compose"
    fi
}

# No --env-file: docker-compose before 1.25 lacks it. Both v1 and v2 read
# .env from the project directory (next to docker-compose.yml) anyway.
function compose_args() {
    echo "--project-name fetcher --project-directory $INSTALL_DIR -f $INSTALL_DIR/docker-compose.yml"
}

# ---------------------------------------------------------------- service

INSTALL_DIR=$(get_install_dir) || { echo "fetcher: install dir not found in qpkg.conf" >&2; exit 1; }
COMPOSE=$(get_compose) || exit 1
# The docker CLI itself: "/x/docker compose" -> "/x/docker", "/x/docker-compose" -> "/x/docker"
DOCKER=${COMPOSE% compose}
DOCKER=${DOCKER%-compose}

case ${1:-} in
    start)
        [ -f "$INSTALL_DIR/.env" ] || {
            echo "fetcher: missing $INSTALL_DIR/.env - run $INSTALL_DIR/setup.sh --no-start over SSH first" >&2
            exit 1
        }
        grep -q "ARIA2_RPC_SECRET=change-me" "$INSTALL_DIR/.env" && {
            echo "fetcher: ARIA2_RPC_SECRET is not configured in .env" >&2
            exit 1
        }
        $COMPOSE $(compose_args) up -d --build
        ;;
    stop)
        $COMPOSE $(compose_args) down
        ;;
    restart)
        $0 stop && $0 start
        ;;
    status)
        # `ps --status` is v2-only; plain docker works with either.
        if [ "$($DOCKER ps -q --filter name=^fetcher-api$ --filter status=running)" ]; then
            echo "fetcher is running"
            exit 0
        else
            echo "fetcher is stopped"
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        ;;
esac
