# Network privacy: what connects where (and how to prove it)

Goal: Fetcher connects **only to the servers you point it at** - no metrics,
no analytics, no phone-home - and keeps a log of every connection so you
don't have to take that on trust.

## How it's enforced

```
browser -> frontnet -> api -> aria2rpc (internal) -> aria2
                        api -> ctlnet (internal)   -> egress control port
                      aria2 -> proxynet (internal) -> egress proxy -> internet
```

* **aria2 has no route to anything but the gateway.** It is attached only to
  `internal: true` networks, so it can't open a connection or even resolve a
  hostname on its own. Its only way out is `fetcher-egress`, a small CONNECT
  proxy (`egress/egress.py`, Python stdlib only).
* **The gateway opens a tunnel only to a host:port you allowed.** When you add
  a link, the API asks the gateway to `prepare` it: the gateway follows the
  redirect chain (one 1-byte `Range` GET per hop, body never read) and allows
  every hop's `host:port`. aria2 then gets the original link.
* **Anything else is refused and logged** - including a server that later
  redirects aria2 to a new host. The download then fails with "Proxy
  connection failed"; re-adding the link re-probes and allows the new hop.
* **LAN/private addresses are refused** (RFC 1918, CGNAT, loopback,
  link-local, ...) unless `FETCHER_ALLOW_LAN=true`. The gateway connects to
  the exact IP it checked, so DNS can't swap in a different address later.
* **No peer-to-peer or fan-out.** magnet/torrent/metalink links are rejected
  by the API, and aria2 runs with `follow-torrent=false`,
  `follow-metalink=false`, DHT/LPD/PEX off and no listening ports. FTP is
  refused too: its data connections go to an address the server picks.
* An allowed host stays allowed for `FETCHER_ALLOW_TTL_DAYS` (default 7) after
  its last use, so resumed downloads keep working after a restart.

## The connection log

Every event is one JSON line in `$DATA_DIR/egress/connections.jsonl` (rotated at
`FETCHER_LOG_MAX_MB`, keeping `FETCHER_LOG_BACKUPS` old files), in
`docker logs fetcher-egress`, and in the UI's **Connections** tab.

| event   | meaning |
|---------|---------|
| `probe` | gateway checked a hop of a link you added (`status` = HTTP status) |
| `allow` | `host:port` added to the allowlist |
| `open`  | aria2 opened a tunnel (`ip` = the address actually connected to) |
| `close` | tunnel closed: `bytes_in`, `bytes_out`, `secs` |
| `deny`  | refused, with `reason` |
| `error` | connect failed |
| `expire`| allowlist entry aged out |
| `start` / `stop` | gateway lifecycle |

```sh
# every distinct destination ever contacted
jq -r 'select(.event=="open") | "\(.target) \(.ip)"' connections.jsonl | sort | uniq -c
# everything that was blocked
jq -c 'select(.event=="deny")' connections.jsonl
```

aria2 keeps connections alive between requests, so a `close` can appear well
after its `open`.

## Inventory of network activity

| Component | Connects to | Why |
|-----------|-------------|-----|
| `fetcher-aria2` | `fetcher-egress` only | all downloads, tunnelled |
| `fetcher-egress` | hosts on the allowlist; DNS via Docker's resolver | the downloads + redirect probes, all logged |
| `fetcher-api` | aria2 RPC + egress control port (internal networks) | forwards your requests |
| your browser | `fetcher-api` on :5142 only | UI - no CDN fonts, external scripts or analytics; the FastAPI `/docs` pages (which load from CDNs) are disabled |
| docker (build time only) | Docker Hub, Alpine mirrors, PyPI | image/package pulls during `docker compose build` |

Notes:

* None of the components has telemetry, update checks or crash reporting.
  FastAPI ships OpenTelemetry hooks; they are switched off explicitly and no
  exporter is installed.
* `fetcher-api` is on `frontnet` (a normal network, needed for its published
  port), so it *could* reach the internet, but its code makes no outbound
  calls. That's the one part not enforced by the network itself.
* The destination server sees your public IP and aria2's User-Agent - true of
  any download client. The gateway's redirect probes use the same
  User-Agent, so each link you add costs the server one extra small request.

## Spot-checking it yourself

1. `docker compose config` - only :5142 is published.
2. `docker exec fetcher-aria2 wget -T5 -O- http://1.1.1.1/` - should fail with
   "Network unreachable": aria2 has no direct route.
3. Add a link, then read the Connections tab or `connections.jsonl`.
4. `scripts/netcheck.sh snap` / `scripts/netcheck.sh 300` - an independent
   view from outside the containers (IPv4 TCP only; the live capture needs
   `sudo tcpdump` on the NAS).

## Residual privacy facts

* Your NAS makes the requests, so the exit IP is your home IP (a VPN changes
  that, not Fetcher).
* `$DATA_DIR/api/fetcher.db` holds your download history (links, file names,
  dates), `$DATA_DIR/aria2/aria2.session` lists unfinished downloads, and
  `$DATA_DIR/egress` holds your connection history. All stay on the server.
