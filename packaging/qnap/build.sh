#!/bin/bash
# Builds the Fetcher QPKG wrapper using QDK (`qbuild`).
#
# The wrapper is arch-independent (it only runs docker compose), so it is
# built from shared/ alone. If your QDK version insists on arch directories,
# add your NAS's arch dir (see `qbuild --create` template, e.g. "x86_64"
# builds use x86; ARM models use the matching arm dir) — it can even be empty.
#
# Prereqs:
#   * QDK installed on the NAS (App Center "Studio" or manually)
#   * docker on the NAS

set -euo pipefail
cd "$(dirname "$0")"

# Bundle the whole stack (compose file + every build context it references)
# so the installed QPKG is self-contained.
for f in docker-compose.yml .env.example .dockerignore setup.sh; do
  cp -f "../../$f" "shared/$f"
done
for d in aria2 api egress web; do
  rm -rf "shared/$d"
  cp -R "../../$d" "shared/$d"
done
find shared -name __pycache__ -prune -exec rm -rf {} +

qbuild "$@"

echo "Done. Install the .qpkg via QTS App Center -> Install from file, then"
echo "over SSH run <InstallPath>/setup.sh --no-start once (it writes .env),"
echo "and start the app from App Center."
