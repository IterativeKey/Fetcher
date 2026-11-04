#!/bin/sh
# Takes ownership of the API's state dir (job history; non-recursive, it's
# ours alone), then runs the API as the unprivileged $PUID:$PGID - the same
# user aria2 downloads as, so "delete file" works on what it wrote and on
# nothing that user couldn't already touch.

set -eu

PUID=${PUID:-1000}
PGID=${PGID:-1000}
STATE_DIR=${STATE_DIR:-/state}

mkdir -p "$STATE_DIR"
chown "$PUID:$PGID" "$STATE_DIR"
for f in "$STATE_DIR"/*; do
  if [ -e "$f" ]; then chown "$PUID:$PGID" "$f"; fi
done

exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups \
  uvicorn app.main:app --host 0.0.0.0 --port 5142 --no-server-header
