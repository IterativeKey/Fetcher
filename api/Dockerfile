# Build context is the repo root (see docker-compose.yml) so the web UI is
# baked into the image: no bind mount, works wherever compose is run from.
FROM python:3.12-slim

WORKDIR /app
COPY api/requirements.txt .
# Exact versions + hashes: a rebuild installs exactly what was reviewed.
RUN pip install --no-cache-dir --disable-pip-version-check --require-hashes -r requirements.txt

COPY api/app ./app
COPY web ./web
COPY api/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh
# Build time, shown in the UI. Docker re-runs this step only when a file
# copied above changed, so it marks when the running code was last rebuilt.
RUN date -u +"%Y-%m-%d %H:%M UTC" > /app/BUILD

# Starts as root only to take ownership of /state, then drops to
# $PUID:$PGID - the same user aria2 writes downloads as, so the API can
# delete them (see entrypoint.sh).
EXPOSE 5142
ENTRYPOINT ["/entrypoint.sh"]
