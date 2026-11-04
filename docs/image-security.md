# How we verify the safety of the Docker images

Fetcher runs **zero third-party application images**. Its three images
(`fetcher-aria2`, `fetcher-egress`, `fetcher-api`) are built from Dockerfiles
in this repo; their ingredients come from trust tiers
we can actually check. This doc explains the model and the concrete commands
to re-verify any image before/while deploying.

## 1. Trust tiers (what we accept and why)

| Tier | Example | Acceptance |
|------|---------|-----------|
| Vendor official (`library/*`) | `alpine:3.20`, `python:3.12-slim` | OK as a base; must be digest-pinned before prod use |
| Signed by distro repos | `apk add aria2 python3` on Alpine | package signatures are verified automatically by apk |
| PyPI, hash-pinned | `api/requirements.txt` | exact versions + sha256 hashes; `pip --require-hashes` refuses anything else |
| Random community images | ~~`p3terx/aria2-pro`~~ (removed) | not accepted — unknown build process, mutable tag |

The old `p3terx/aria2-pro` fails this policy: you cannot see its full Dockerfile
chain, the `latest` tag silently changes, and there is no verifiable signature.
Our replacement is `aria2/Dockerfile`: official Alpine base + distro-packaged
aria2, owned-volume reads/writes only, runs as `$PUID:$PGID` (non-root), and
aria2's RPC secret sits in a 600-perm config.

## 2. Verify a specific image yourself (the commands)

### a) Read what you actually run

```sh
docker history --no-trunc fetcher-aria2          # every layer + its Dockerfile instruction
docker image inspect fetcher-aria2               # config entrypoint, caps, mounts
docker save fetcher-aria2 | tar -tz              # list every file shipped in the image
docker run --rm --entrypoint sh fetcher-aria2    # poke around interactively
```

`scripts/scan.sh` automates 1 and 2 per image.

### b) Check provenance on Docker Hub

For any image you didn't build: open its Hub page → does it show a linked,
public source repo? Is it a "verified build" (built by Hub from that repo)?
Read its Dockerfile's own `FROM` chain. Check the "Last updated" date and
download count. No public source → treat as untrusted.

### c) Freezing a base image to an immutable digest

A tag (`3.20`) can be repointed by its owner; a digest cannot.

```sh
docker pull alpine:3.20
docker image inspect alpine:3.20 --format '{{index .RepoDigests 0}}'
# e.g. alpine@sha256:51b67269fdd6...  -> use exactly this in FROM
```

Change `FROM alpine:${ALPINE_VERSION}` to `FROM alpine@sha256:<digest>` once
you're happy with the version you reviewed. Re-pinning deliberately (a manual
step + a re-scan) is the update process — never `--pull always` prod images.

### d) Vulnerability + secret scanning

```sh
scripts/scan.sh            # trivy: HIGH/CRITICAL, unfixed-only, fails on findings
trivy image --scanners vuln,secret,config --format cyclonedx fetcher-api > sbom.json   # SBOM
# alternative scanners: grype, dockle (linter for container best practices)
```

Add a recurring job (cron) so scanning is not a one-off: rebuild monthly,
re-scan, digest re-pin only reviewed bases.

### e) Signatures (when a publisher offers one)

```sh
cosign verify --key /path/to/publisher.pub <image>@sha256:<digest>
```

If a project publishes cosign signatures, pin the digest AND verify it before
allowing the image inside the NAS. If they don't sign, (b)+(d) carry the weight.

## 3. Runtime guardrails (defense in depth, per image)

* **Network**: only `5142` (UI/API) is published. aria2 sits on internal-only
  networks; its RPC is reachable only from the api container, and its only
  way out is the egress gateway (see docs/network-privacy.md).
* **Filesystem**: all three containers run `read_only: true` + a tmpfs. aria2
  writes only `/config` and `/downloads`, the gateway and the API only their
  own `/state`; the API also mounts `/downloads`, to serve, rename and delete
  files - only ones its history recorded as Fetcher's own (`api/app/files.py`).
  The download share is never chowned; keep the app and `DATA_DIR` outside it.
* **Processes**: every container drops all capabilities and keeps only
  CHOWN/SETUID/SETGID, so its entrypoint can take ownership of its own state
  dir and then drop to `$PUID:$PGID` (`su-exec` on alpine, `setpriv` in the
  API image) - after which the process has no capabilities at all. The API
  runs as the same user as aria2 so it can delete what aria2 wrote. All run
  with `no-new-privileges` and a read-only root filesystem.
* **API surface**: a token is required for every call (file links are
  signed with it and expire); clients can't pass aria2 options - the only
  per-download values are a folder name and a speed limit, validated and
  turned into options by the API (no `dir`/`out`/`allow-overwrite` tricks);
  only http(s) links. Served files get a sandbox CSP and `nosniff`.
* **Secrets**: `ARIA2_RPC_SECRET` and `FETCHER_API_TOKEN` live only in `.env`
  (+ aria2's 600-perm conf); never commit `.env`.

## 4. QNAP-specific notes

* Container Station pulls from Docker Hub by tag — prefer building on the NAS
  from this repo (`docker compose up -d --build`) rather than letting it pull
  `:latest` of anything.
* QTS firmware updates can push Container Station/docker versions silently;
  after a firmware update re-run `scripts/scan.sh` and re-check `docker compose ps`.

## 5. TL;DR checklist before going live

- [ ] `docker history --no-trunc` read for all three images (or trust our Dockerfiles, you have them)
- [ ] base images digest-pinned in all three Dockerfiles
- [ ] `scripts/scan.sh` clean (or findings triaged)
- [ ] `.env` has fresh `ARIA2_RPC_SECRET` and `FETCHER_API_TOKEN` values
- [ ] app + state dirs are outside `DOWNLOAD_DIR`
- [ ] `docker compose config` reviewed — only the intended ports/volumes
