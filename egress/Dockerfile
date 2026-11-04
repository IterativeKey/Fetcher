# Fetcher's egress gateway: official Alpine + distro python3, our own
# stdlib-only script. Same trust model as aria2/Dockerfile.
ARG ALPINE_VERSION=3.20
FROM alpine:${ALPINE_VERSION}

RUN apk add --no-cache python3 su-exec ca-certificates

COPY egress.py /app/egress.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
