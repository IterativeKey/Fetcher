#!/bin/sh
# Fetcher first-time setup: writes .env, creates folders, checks the system,
# then builds and starts the stack. Safe to run again: an existing .env is
# kept (use --reconfigure to write a new one; secrets are kept).
#
#   ./setup.sh                 interactive
#   ./setup.sh --yes           accept every default (DOWNLOAD_DIR etc. can be
#                              preset in the environment)
#   ./setup.sh --no-start      only write .env and check, don't start
#
# POSIX sh only: runs on BusyBox (QNAP, Synology), Linux and macOS.

set -eu
cd "$(dirname "$0")"
APP_DIR=$(pwd -P)

YES=0; START=1; RECONF=0
for a in "$@"; do
  case $a in
    -y|--yes) YES=1 ;;
    --no-start) START=0 ;;
    --reconfigure) RECONF=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

ask() { # ask "question" default -> answer on stdout
  if [ "$YES" = 1 ] || [ ! -t 0 ]; then printf '%s' "$2"; return; fi
  printf '%s [%s]: ' "$1" "$2" >&2
  read -r ans || ans=""
  printf '%s' "${ans:-$2}"
}

confirm() { # confirm "question" -> 0 if yes (default yes)
  [ "$YES" = 1 ] && return 0
  printf '%s [Y/n]: ' "$1" >&2
  read -r ans || ans=""
  case $ans in n|N|no|NO) return 1 ;; *) return 0 ;; esac
}

abspath() { (cd "$1" 2>/dev/null && pwd -P); }

file_uid() { stat -c %u "$1" 2>/dev/null || stat -f %u "$1"; }
file_gid() { stat -c %g "$1" 2>/dev/null || stat -f %g "$1"; }

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    od -An -N16 -tx1 /dev/urandom | tr -d ' \n'
  fi
}

env_get() { # env_get KEY -> value from .env (or empty)
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | tail -n1
}

# ------------------------------------------------------------- platform

PLATFORM=linux
if [ -f /etc/config/qpkg.conf ] || [ -d /share/CACHEDEV1_DATA ]; then
  PLATFORM=qnap
elif [ -f /etc/synoinfo.conf ]; then
  PLATFORM=synology
elif [ "$(uname -s)" = Darwin ]; then
  PLATFORM=macos
fi
say "Fetcher setup ($PLATFORM)"

# ------------------------------------------------------------- docker

DOCKER=""
for d in "$(command -v docker 2>/dev/null || true)" /usr/local/bin/docker /usr/bin/docker \
         /share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker; do
  if [ -n "$d" ] && [ -x "$d" ]; then DOCKER=$d; break; fi
done
[ -n "$DOCKER" ] || die "docker not found. On QNAP install Container Station; on Synology, Container Manager; elsewhere, Docker Engine."
"$DOCKER" info >/dev/null 2>&1 || die "docker is installed but not running, or this user can't use it (try sudo, or add the user to the docker group)."

if "$DOCKER" compose version >/dev/null 2>&1; then
  COMPOSE="$DOCKER compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=docker-compose
elif [ -x "$(dirname "$DOCKER")/docker-compose" ]; then
  COMPOSE="$(dirname "$DOCKER")/docker-compose"
else
  die "neither 'docker compose' nor 'docker-compose' found."
fi
say "docker:  $("$DOCKER" version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
say "compose: $($COMPOSE version --short 2>/dev/null || $COMPOSE version | head -n1)"

# ------------------------------------------------------------- .env

if [ -f .env ] && [ "$RECONF" = 0 ]; then
  say "Using the existing .env (run with --reconfigure to change it)."
else
  # Secrets: keep existing ones so a reconfigure doesn't log the UI out.
  SECRET=$(env_get ARIA2_RPC_SECRET); TOKEN=$(env_get FETCHER_API_TOKEN)
  [ -n "$SECRET" ] && [ "$SECRET" != change-me ] || SECRET=$(gen_secret)
  [ -n "$TOKEN" ] || TOKEN=$(gen_secret)

  case $PLATFORM in
    qnap)
      vol=$(ls -d /share/CACHEDEV*_DATA 2>/dev/null | head -n1)
      DEF_DL=${DOWNLOAD_DIR:-$vol/Fetcher}
      say "QNAP tip: create the download folder as a Shared Folder in QTS first, so it shows in File Station." ;;
    synology)
      DEF_DL=${DOWNLOAD_DIR:-/volume1/downloads} ;;
    *)
      DEF_DL=${DOWNLOAD_DIR:-$APP_DIR/downloads} ;;
  esac
  DL=$(ask "Download folder (absolute path)" "$DEF_DL")
  DATA=$(ask "Fetcher's own data folder" "${DATA_DIR:-$APP_DIR/data}")
  case $DL in /*) ;; *) die "use an absolute path for the download folder" ;; esac
  case $DATA in /*) ;; *) DATA="$APP_DIR/$DATA" ;; esac

  if [ ! -d "$DL" ]; then
    confirm "Create $DL?" || die "create the folder first, then run setup again"
    mkdir -p "$DL" || die "could not create $DL (try sudo)"
  fi
  mkdir -p "$DATA" || die "could not create $DATA"

  # Nothing a download writes may land on top of the app or its state.
  DLR=$(abspath "$DL"); DATAR=$(abspath "$DATA")
  case "$APP_DIR/" in "$DLR"/*) die "the app folder ($APP_DIR) is inside the download folder - move one of them" ;; esac
  case "$DATAR/" in "$DLR"/*) die "the data folder is inside the download folder - pick another" ;; esac

  # Run as the download folder's owner, unless that's root: never run the
  # engine as root.
  U=$(file_uid "$DL"); G=$(file_gid "$DL")
  if [ "$U" = 0 ]; then
    me=$(id -u)
    if [ "$me" != 0 ]; then U=$me; G=$(id -g)
    else
      U=$(ask "The folder is owned by root. Numeric user ID to download as (see: id <user>)" 1000)
    fi
  fi
  # Group 0 is root's group: use the user's own group instead (QNAP: everyone).
  if [ "$G" = 0 ]; then
    if [ "$PLATFORM" = qnap ]; then G=100
    elif [ "$(id -g)" != 0 ]; then G=$(id -g)
    else G=1000; fi
  fi
  PUID=$(ask "Download as user ID" "$U")
  PGID=$(ask "Download as group ID" "$G")
  [ "$PUID" != 0 ] || die "refusing to run downloads as root (user ID 0) - pick a regular user"

  PORT=$(ask "Web UI port" "${FETCHER_PORT:-5142}")

  umask 077
  sed -e "s|^ARIA2_RPC_SECRET=.*|ARIA2_RPC_SECRET=$SECRET|" \
      -e "s|^FETCHER_API_TOKEN=.*|FETCHER_API_TOKEN=$TOKEN|" \
      -e "s|^DOWNLOAD_DIR=.*|DOWNLOAD_DIR=$DL|" \
      -e "s|^DATA_DIR=.*|DATA_DIR=$DATA|" \
      -e "s|^PUID=.*|PUID=$PUID|" \
      -e "s|^PGID=.*|PGID=$PGID|" \
      -e "s|^FETCHER_PORT=.*|FETCHER_PORT=$PORT|" \
      .env.example > .env.tmp
  mv .env.tmp .env
  umask 022
  say "Wrote .env (readable only by you)."
fi

# ------------------------------------------------------------- checks

DL=$(env_get DOWNLOAD_DIR); DATA=$(env_get DATA_DIR); PORT=$(env_get FETCHER_PORT)
PORT=${PORT:-5142}; TOKEN=$(env_get FETCHER_API_TOKEN)
case $DL in /*) ;; *) DL="$APP_DIR/${DL#./}" ;; esac
case $DATA in /*) ;; *) DATA="$APP_DIR/${DATA#./}" ;; esac
mkdir -p "$DL" "$DATA/aria2" "$DATA/egress" "$DATA/api"

[ "$(env_get ARIA2_RPC_SECRET)" != change-me ] || die "ARIA2_RPC_SECRET in .env is still 'change-me'"
[ -n "$TOKEN" ] || die "FETCHER_API_TOKEN in .env is empty"

if (netstat -tln 2>/dev/null || ss -tln 2>/dev/null) | grep -q "[:.]$PORT[[:space:]]"; then
  if ! "$DOCKER" ps --format '{{.Names}}' 2>/dev/null | grep -q '^fetcher-api$'; then
    warn "port $PORT is already in use by something else - set FETCHER_PORT in .env"
  fi
fi

$COMPOSE config -q || die "the compose file didn't validate with $COMPOSE (see above)"
say "Checks passed."

[ "$START" = 1 ] || { say "Not starting (--no-start). Start with: $COMPOSE up -d --build"; exit 0; }
confirm "Build and start Fetcher now?" || exit 0

$COMPOSE up -d --build

# ------------------------------------------------------------- wait & report

say "Waiting for Fetcher to come up..."
ok=0; i=0
while [ $i -lt 60 ]; do
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -H "X-Fetcher-Token: $TOKEN" "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && ok=1
  else
    wget -q -O /dev/null --header "X-Fetcher-Token: $TOKEN" "http://127.0.0.1:$PORT/api/health" 2>/dev/null && ok=1
  fi
  [ $ok = 1 ] && break
  # A container stuck restarting won't fix itself: show why right away.
  for c in fetcher-aria2 fetcher-egress fetcher-api; do
    [ "$("$DOCKER" inspect -f '{{.State.Restarting}}' "$c" 2>/dev/null)" = true ] && i=999
  done
  i=$((i + 1)); sleep 2
done

IP=$( (ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p') || true)
[ -n "$IP" ] || IP=$(hostname -I 2>/dev/null | cut -d' ' -f1 || true)
[ -n "$IP" ] || IP=$(ipconfig getifaddr en0 2>/dev/null || true)
[ -n "$IP" ] || IP=localhost

if [ $ok = 1 ]; then
  say ""
  say "Fetcher is running:  http://$IP:$PORT"
  say "Token (the UI asks once):  $TOKEN"
  say "Downloads go to:  $DL"
else
  warn "Fetcher didn't answer on port $PORT yet. Recent logs:"
  $COMPOSE logs --tail 30 || true
  exit 1
fi
