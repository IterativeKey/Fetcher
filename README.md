# Fetcher

A self-hosted, resumable, multi-connection download manager with a web UI.
Paste a link, and your server (a NAS, a home server, any Linux box with
Docker) downloads it; manage, save to your device, or delete it from any
browser. Plain http(s) links only - no torrents.

Built as a **Docker Compose stack** (download engine + egress gateway + API +
UI). It runs anywhere Docker does. On QNAP it can also be wrapped in a
**QPKG** for a Main Menu icon and start/stop from App Center.

## Features

- **Downloads:** multi-connection, resumable across restarts; paste or drop
  many links at once; save into folders; add paused; queue order (top/bottom);
  per-download and overall speed limits; how many run at once.
- **Automatic retry:** a download that fails for a temporary reason (503/429,
  a dropped TLS connection, a timeout, "No URI available.") is resumed
  automatically after 30 s, 1 min, 2 min ... up to 1 h, 8 times, with fewer
  connections each time (8, 4, 2, 1) for servers that throttle. 404s, auth
  and disk errors are not retried. Cancel or retry now from the row menu.
- **History:** every download stays in the list after it finishes (and after
  restarts) until you remove it. Favorite, hide/show hidden, search, filter
  by status or folder, sort, select many for bulk actions.
- **Files:** save to this device (any browser, resumable), open images,
  video, audio and text in a tab, rename, SHA-256, **delete from disk** -
  only ever for files Fetcher itself downloaded (see below).
- **Privacy:** the engine can only reach the hosts of links you added, and
  every connection it makes is logged and shown in the Connections tab. No
  telemetry, no update checks, no third-party assets.
- **UI:** light/dark, works on phones, keyboard shortcuts (`/` search, `n`
  add, `Esc` clear selection, `Del` remove selected), optional
  notifications when a download finishes.

## Quick start

Needs Docker with either `docker compose` (v2) or `docker-compose` (v1.21+).

```sh
./setup.sh
```

`setup.sh` asks where downloads should go (everything else has a default),
generates the secrets, picks the user to download as, checks the port and
the compose file, then builds and starts Fetcher and prints the URL and the
token the UI asks for. Run it again any time; `./setup.sh --reconfigure`
changes the settings (secrets are kept), `--yes` accepts all defaults.

Prefer doing it by hand? `cp .env.example .env`, fill in the two secrets
(`openssl rand -hex 16`) and `DOWNLOAD_DIR`, then `docker compose up -d --build`.

## Platform notes

### QNAP (QTS)

1. In QTS, install **Container Station** and create a **Shared Folder** for
   downloads (e.g. `Fetcher`).
2. Enable SSH and find the volume your share is on:
   `readlink -f /share/Fetcher` (e.g. `/share/CACHEDEV1_DATA/Fetcher`, or
   `/share/CE_CACHEDEV1_DATA/Fetcher` on some models). Use that real path
   everywhere: `/share` itself is a 16 MiB RAM disk, so a path that doesn't
   exist gets created there and is wiped on reboot.
3. Copy this repo **outside** the share, on the same volume, e.g.
   `/share/CE_CACHEDEV1_DATA/FetcherApp`.
4. `cd` there and run `./setup.sh`. It suggests the share on the first
   storage volume and the group `everyone` (100), stores real paths, and
   refuses folders on a RAM disk.
5. Optional: the QPKG wrapper for a Main Menu icon - see
   `packaging/qnap/build.sh`. It needs [QDK](https://github.com/qnap-dev/QDK)
   on the NAS; install the `.qpkg` via **App Center -> Install from file**
   (an unsigned-package warning is expected), run
   `<InstallPath>/setup.sh --no-start` once, then start it from App Center.
   The UI uses relative paths so it also works under QTS's `/fetcher` proxy
   path; whether that proxy passes the live-update WebSocket is untested
   (`http://NAS:5142` always works).

Older QTS versions ship the Python `docker-compose` v1; the compose file is
format 2.4 on purpose so it works there too.

### Synology, Unraid, any Linux

Run `./setup.sh` and point the download folder at a share
(e.g. `/volume1/downloads` on Synology).

## Deleting files safely

Fetcher's history records each file as it is written, and the API only ever
serves, renames or deletes a file when **all** of these hold:

- it is in the history as downloaded by Fetcher (there is no way to name
  another path, and no directory listing);
- it is inside the download folder, with no symlink anywhere in its path;
- it is a regular file owned by the user Fetcher runs as;
- its device and inode match what was recorded, and (once finished) its size
  and modification time too - so a file someone replaced, even one that
  reused the same inode number, is refused.

Deleting asks for confirmation. "Delete file" keeps the entry (marked
deleted, so you can download it again); "Delete file and remove" drops both.

Browser downloads use links signed with the token that expire after 5
minutes (`FETCHER_LINK_TTL`); the token itself never appears in a URL. Files
are served with a sandbox CSP, so nothing from the download folder can run
script on Fetcher's page.

## Architecture

```
[browser]  ──▶  [fetcher-api :5142]     REST + WebSocket + UI, token required;
                    │       │            job history (SQLite) in DATA_DIR/api
        JSON-RPC    │       │  "allow this link"
       (internal)   ▼       ▼  (internal)
             [fetcher-aria2]  ── CONNECT ──▶  [fetcher-egress]  ──▶  only the hosts
               segmented, resumable;          allowlist + log of        of links you
               no route out except            every connection          added
               through the gateway
                    │
                    ▼
             DOWNLOAD_DIR          the ONLY directory downloads can touch
```

Only the UI port (5142) is published. aria2 sits on internal-only networks,
so it can reach nothing but the egress gateway, which tunnels only to hosts
you added and logs every attempt. The API runs as the same user as aria2
(`PUID`/`PGID`), so it can delete what aria2 wrote and nothing that user
couldn't already touch. See `docs/network-privacy.md`.

## Layout

```
setup.sh               first-time setup (POSIX sh: BusyBox, Linux, macOS)
docker-compose.yml     the stack (format 2.4: compose v1 and v2)
.env.example           settings reference (setup.sh writes .env from it)
aria2/                 engine image (official alpine + distro aria2)
egress/                egress gateway (official alpine + stdlib python3)
api/                   FastAPI service (Python 3.12, hash-pinned deps)
  app/main.py            REST + WebSocket, actions, sync loop
  app/db.py              job history (SQLite)
  app/files.py           every disk operation and its safety checks
  app/aria2_client.py    aria2 JSON-RPC client
web/                   the UI (no third-party assets), baked into the api image
packaging/qnap/        optional QPKG wrapper (qpkg.cfg, build.sh, service script)
scripts/scan.sh        trivy vulnerability/secret scan + image history audit
scripts/netcheck.sh    egress auditor: open connections + live WAN capture
docs/                  image security, network privacy, project status
```

State lives in `DATA_DIR` (default `./data`): `api/fetcher.db` (history),
`aria2/` (engine session), `egress/` (allowlist + connection log). Back up
that folder to keep your history.

## API

Every `/api` call needs the header `X-Fetcher-Token: <token>`. WebSocket
clients send the token as their first message instead, so it never appears
in a URL or access log.

```
GET    /api/health                      liveness + aria2 version
GET    /api/state                       history + live progress + settings + disk
POST   /api/downloads                   {urls: [...], category?, paused?} -> per-link results
PATCH  /api/downloads/{id}              {favorite?, hidden?, speed_limit?}
POST   /api/downloads/{id}/{action}     pause | resume | stop | retry | top | bottom |
                                        favorite | unfavorite | hide | unhide |
                                        delete-file | remove | remove-and-delete
POST   /api/downloads/{id}/rename       {name}   (finished downloads, never overwrites)
POST   /api/downloads/{id}/checksum     -> {sha256}
POST   /api/downloads/{id}/link?inline= -> {url}  short-lived signed file link
GET    /api/files/{id}?exp&inline&sig   the file (signed link, no token header)
DELETE /api/downloads/{id}?delete_file= remove from the list (and the file)
POST   /api/bulk                        {ids: [...], action}
POST   /api/global/{pause|resume}       all downloads
GET|PUT /api/settings                   {speed_limit (bytes/s, 0 = none), max_concurrent}
GET    /api/connections?limit=N         the egress gateway's connection log
WS     /api/events                      full snapshot on change, live progress every 1s
```

Links are rejected up front if they are magnet/torrent/metalink, not
http(s), resolve to a LAN address (unless `FETCHER_ALLOW_LAN=true`), or can't
be reached. A file whose name already exists is saved as `name.1.ext`, never
overwritten.

## Verifying image safety

See `docs/image-security.md`. In short: no community images; all three
images are built from Dockerfiles in this repo on official bases, Python
deps are hash-pinned, and `scripts/scan.sh` (trivy: HIGH/CRITICAL + secret
scan) should pass before deploying.

## Status

Early (0.5.0). Tested end to end in Docker with both `docker compose` v2 and
`docker-compose` v1.29.2 (the legacy builder). Not yet run on a real NAS;
see `docs/STATUS.md` for what's verified and what's open. Reports welcome.

## License

MIT - see [LICENSE](LICENSE).
