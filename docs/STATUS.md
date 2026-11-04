# Project status — 2026-11-04

## Where things stand

Nothing is committed yet: every file in the repo is untracked. The first
commit should be the current state.

History: a 2026-10-23 review found the original code broken and unsafe; that
was fixed and an egress gateway added (2026-10-24). On 2026-11-04 the project
was made platform-neutral and old-compose compatible, got a first-time
`setup.sh`, a job history, file serving/deletion with strict ownership
checks, and a rebuilt UI.

## Verified (2026-11-04, local Docker on colima)

Scripted end-to-end API test (28 checks), passing under **both**
`docker compose` v2 (5.7.0) and `docker-compose` **v1.29.2** with the legacy
builder:

- Auth required; only http(s); magnet/ftp/LAN links and bad folder names
  refused. Add paused, into a folder; resume; completes.
- Save to device: signed link without the token, correct size, `attachment`
  + sandbox CSP, Range requests (206); tampered/invalid signatures refused.
- SHA-256, rename (refuses `../`), favorite/hide stored, link still valid
  after rename.
- **Delete safety**: a file replaced after download by another file of the
  same name, written by the same user, right after the original was deleted
  (so the inode number was reused) is neither deleted nor served. This test
  caught a real bug - inode-only identity - fixed by also checking owner,
  size and mtime.
- Delete file keeping the entry; bulk remove+delete; download again creates
  a new entry; stop keeps progress and the partial file; retry resumes the
  same file (no `.1` copy); settings saved; history and unfinished
  downloads survive an api+aria2 restart; cancel+delete removes the partial.
- aria2 still has no direct route and no DNS; the API runs as `PUID:PGID`
  with no capabilities and a read-only root.
- `setup.sh --yes` end to end (writes `.env`, starts, waits for health,
  prints URL + token; detects a crash-looping container and shows its logs).
  Parses under BusyBox `sh`.
- UI in headless Brave: sign-in dialog, list in light/dark, row menu,
  details, bulk bar, search/tabs/hidden filters, Connections tab, settings,
  save-to-device link, add with a failing link kept in the box, phone width
  without horizontal scroll; no JS errors.

## Not verified

- **A real NAS.** QNAP's Docker version, Container Station's compose,
  permissions on a real share, `PUID`/`PGID` defaults, ARM models.
- The QPKG: `qbuild` with `packaging/qnap/qpkg.cfg`, the service script on
  QTS, and whether the QTS `/fetcher` proxy passes WebSockets.
- CI has not run yet (needs the first push). It now also validates the
  compose file with docker-compose v1.29.2 and `setup.sh` with `dash`.
- Desktop notifications (need HTTPS or localhost; on plain-http LAN the UI
  falls back to an in-page message).

## Open items

- [ ] Commit the current state.
- [ ] Test on the NAS: `./setup.sh`, add/serve/delete, restart the NAS.
- [ ] Pin base image digests (`alpine:3.20` x2, `python:3.12-slim`).
- [x] Pin `aquasecurity/trivy-action` (v0.36.0) and `actions/checkout` (v7.0.1) to commit SHAs.
- [ ] FTP support, if needed: its data connections go to a server-chosen
      address, which doesn't fit the host allowlist.
- [ ] The api container sits on a normal network (needed to publish :5142),
      so the network doesn't stop it from reaching the internet; only its
      code doesn't. aria2 is the locked-down one.
- [ ] Known tradeoffs: one 1-byte probe request per link hop; the allowlist
      is shared across links (7-day TTL since last use); a CDN redirecting
      to a new host mid-download fails until the link is re-added.
- [ ] Some servers refuse many connections (Hetzner: HTTP 429 at 16); the
      default is now 8 per server. Some don't support ranges at all
      (Cloudflare's speed test) - those can't resume.
- [ ] `scripts/netcheck.sh snap` reads only IPv4 TCP (`/proc/net/tcp`).
- [ ] Files that existed before the history (or downloads adopted from
      aria2 without a recorded identity) can't be served or deleted from the
      UI, by design.
