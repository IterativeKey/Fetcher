# Fetcher's own aria2 image: avoids third-party images like p3terx/aria2-pro.
#
# Trust model:
#   * Base image is official Alpine (`library/alpine`), first pinned to a
#     version tag, then to an immutable digest — see docs/image-security.md.
#   * aria2 comes from Alpine's signed package repos (apk verifies signatures).
#
# To freeze the base image:   docker pull alpine:3.20
#   docker image inspect alpine:3.20 --format '{{index .RepoDigests 0}}'
# then change FROM to:        alpine@sha256:<digest>

ARG ALPINE_VERSION=3.20
FROM alpine:${ALPINE_VERSION}

RUN apk add --no-cache aria2 tzdata su-exec

COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

# Runs as root only long enough to fix volume ownership, then drops to
# $PUID:$PGID (see entrypoint.sh) — aria2 itself never runs privileged.
ENTRYPOINT ["/entrypoint.sh"]
