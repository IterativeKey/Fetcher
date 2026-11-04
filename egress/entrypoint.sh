#!/bin/sh
# Takes ownership of the state dir (allowlist + connection logs; non-recursive,
# it's ours alone), then runs the gateway as the unprivileged $PUID:$PGID.

set -eu

PUID=${PUID:-1000}
PGID=${PGID:-1000}
STATE_DIR=${STATE_DIR:-/state}

mkdir -p "$STATE_DIR"
chown "$PUID:$PGID" "$STATE_DIR"
for f in "$STATE_DIR"/*; do
  if [ -e "$f" ]; then chown "$PUID:$PGID" "$f"; fi
done

exec su-exec "$PUID:$PGID" python3 -u /app/egress.py
