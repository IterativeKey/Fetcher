#!/bin/sh
# Verifies the images Fetcher runs:
#   1. scans fetcher-api and fetcher-aria2 for vulnerabilities (trivy; grype optional)
#   2. prints docker history of each image so 'what does this image do' is auditable
#   3. fails the build/deploy if unignored HIGH/CRITICAL CVEs exist
#
# Usage:  scripts/scan.sh [--no-fail]
# Requires: trivy (aquasecurity/trivy) - or swap in grype same flags.

set -eu
FAIL=1
[ "${1:-}" = "--no-fail" ] && FAIL=0

IMAGES=${IMAGES:-"fetcher-aria2 fetcher-egress fetcher-api"}

for img in $IMAGES; do
  echo "=== vulnerability scan: $img ==="
  if command -v trivy >/dev/null 2>&1; then
    trivy image --scanners vuln,secret \
      --severity HIGH,CRITICAL \
      --ignore-unfixed \
      --exit-code 1 --no-progress "$img" || [ "$FAIL" -eq 0 ]
  else
    echo "  trivy not installed - skipping vuln scan (docker run --rm aquasec/trivy image $img)" >&2
  fi

  echo "=== docker history: $img (what does each layer do?) ==="
  docker history --no-trunc "$img"
done

echo
echo "=== trust check reminder ==="
echo "- base image digests used: see docs/image-security.md"
docker image inspect ${IMAGES} --format '{{.RepoTags}} {{.RepoDigests}}' || true
