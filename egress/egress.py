"""Fetcher egress gateway: the download engine's only way out, and its log.

aria2 sits on internal-only networks; its sole route anywhere is this
CONNECT proxy. A tunnel is opened only to a host:port that the API allowed
when you added a link, and only if that host resolves to a public address.
Every attempt - allowed or denied - is appended to connections.jsonl.

Control endpoint (reachable only by the api container):
  POST /prepare {"url"}   follow the link's redirect chain, allow each hop
  GET  /log?limit=N       newest connection events
  GET  /allowlist         hosts aria2 may currently reach
  GET  /health

Standard library only, so there is nothing third-party to vet.
"""

import asyncio
import collections
import http.client
import ipaddress
import json
import logging
import os
import signal
import socket
import ssl
import struct
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, urljoin, urlsplit

STATE_DIR = os.getenv("STATE_DIR", "/state")
PROXY_PORT = int(os.getenv("PROXY_PORT", "3128"))
CTL_PORT = int(os.getenv("CTL_PORT", "8081"))
# Only this container may use the control endpoint. aria2 can reach this
# container too (that's how it gets out), so it must not be able to allow
# hosts for itself.
CTL_CLIENT = os.getenv("CTL_CLIENT", "api")
ALLOW_LAN = os.getenv("FETCHER_ALLOW_LAN", "false").lower() in ("1", "true", "yes")
ALLOW_TTL = float(os.getenv("FETCHER_ALLOW_TTL_DAYS", "7")) * 86400
LOG_MAX_BYTES = int(os.getenv("FETCHER_LOG_MAX_MB", "10")) * 1024 * 1024
LOG_BACKUPS = int(os.getenv("FETCHER_LOG_BACKUPS", "9"))
# Sent while probing redirects, so servers answer as they will for aria2.
USER_AGENT = os.getenv("PROBE_USER_AGENT", "aria2/1.37.0")
MAX_HOPS = 10
CONNECT_TIMEOUT = 30
REDIRECTS = {301, 302, 303, 307, 308}

ALLOWLIST_FILE = os.path.join(STATE_DIR, "allowlist.json")
LOG_FILE = os.path.join(STATE_DIR, "connections.jsonl")


class Denied(Exception):
    pass


# --- connection log -----------------------------------------------------------

_log = logging.getLogger("connections")
_recent = collections.deque(maxlen=2000)


def setup_log() -> None:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(handler)
    _log.addHandler(logging.StreamHandler())  # docker logs fetcher-egress
    _log.setLevel(logging.INFO)
    _log.propagate = False
    try:  # seed the UI's view with what's already on disk
        with open(LOG_FILE) as f:
            for line in collections.deque(f, maxlen=_recent.maxlen):
                _recent.append(json.loads(line))
    except (OSError, ValueError):
        pass


def record(event: str, **fields) -> None:
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
             "event": event, **{k: v for k, v in fields.items() if v is not None}}
    _recent.append(entry)
    _log.info(json.dumps(entry, separators=(",", ":")))


# --- address policy ------------------------------------------------------------

def norm_host(host: str) -> str:
    host = host.strip().strip("[]").rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def internal_subnets() -> list[ipaddress.IPv4Network]:
    """Subnets of this container's internal networks (proxynet, ctlnet).

    That's every interface except the one carrying the default route. They're
    refused even with FETCHER_ALLOW_LAN, so a link can't point aria2 at
    Fetcher's own containers. Read live on every check: networks can be
    attached after this process starts.
    """
    routes = []
    with open("/proc/net/route") as f:
        next(f)
        for line in f:
            iface, dest, _gw, _flags, _, _, _, mask = line.split()[:8]
            routes.append((iface, int(dest, 16), int(mask, 16)))
    default_ifaces = {iface for iface, dest, mask in routes if dest == 0 and mask == 0}
    to_ip = lambda n: socket.inet_ntoa(struct.pack("<I", n))
    return [ipaddress.IPv4Network(f"{to_ip(dest)}/{to_ip(mask)}")
            for iface, dest, mask in routes
            if mask and iface not in default_ifaces]


def addr_allowed(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%", 1)[0])
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    if a.is_loopback or a.is_unspecified or a.is_multicast or a.is_link_local:
        return False
    if any(a in net for net in internal_subnets()):
        return False
    return True if ALLOW_LAN else a.is_global


def check_addrs(host: str, ips: list[str]) -> None:
    bad = [ip for ip in ips if not addr_allowed(ip)]
    if bad:
        raise Denied(f"{host} resolves to a non-public address ({bad[0]})"
                     + ("" if ALLOW_LAN else "; set FETCHER_ALLOW_LAN=true for LAN hosts"))


def resolve_sync(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise Denied(f"cannot resolve {host}: {exc.strerror}")
    ips = list(dict.fromkeys(i[4][0] for i in infos))
    check_addrs(host, ips)
    return ips


async def resolve(host: str, port: int) -> list[str]:
    return await asyncio.get_running_loop().run_in_executor(None, resolve_sync, host, port)


# --- allowlist -------------------------------------------------------------------

allowlist: dict[str, dict] = {}  # "host:port" -> {"added", "last_used", "url"}


def load_allowlist() -> None:
    try:
        with open(ALLOWLIST_FILE) as f:
            allowlist.update(json.load(f))
    except (OSError, ValueError):
        pass
    expire_allowlist()


def save_allowlist() -> None:
    tmp = ALLOWLIST_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(allowlist, f, indent=1)
    os.replace(tmp, ALLOWLIST_FILE)


def expire_allowlist() -> None:
    cutoff = time.time() - ALLOW_TTL
    for key in [k for k, v in allowlist.items() if v["last_used"] < cutoff]:
        del allowlist[key]
        record("expire", target=key)


def allow(host: str, port: int, url: str) -> None:
    key = f"{host}:{port}"
    now = time.time()
    entry = allowlist.setdefault(key, {"added": now, "url": url})
    entry["last_used"] = now
    record("allow", target=key, url=url)


# --- redirect probe (runs in a worker thread) ----------------------------------------

class PinnedHTTP(http.client.HTTPConnection):
    """Connects to an already-vetted IP, so DNS can't change between check and use."""

    def __init__(self, host, port, ip, **kw):
        super().__init__(host, port, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, **kw):
        super().__init__(host, port, context=ssl.create_default_context(), **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def probe_chain(url: str) -> list[tuple[str, str, int]]:
    """Follow url's redirects; return (url, host, port) for every hop.

    Each hop is a GET for one byte (Range: bytes=0-0); the body is never read.
    """
    hops = []
    for _ in range(MAX_HOPS + 1):
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https") or not parts.hostname:
            raise Denied(f"redirect to unsupported URL: {url[:200]}")
        host = norm_host(parts.hostname)
        port = parts.port or (443 if scheme == "https" else 80)
        ip = resolve_sync(host, port)[0]
        hops.append((url, host, port))

        cls = PinnedHTTPS if scheme == "https" else PinnedHTTP
        conn = cls(host, port, ip, timeout=CONNECT_TIMEOUT)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        try:
            conn.request("GET", target, headers={
                "User-Agent": USER_AGENT, "Accept": "*/*", "Range": "bytes=0-0"})
            resp = conn.getresponse()
            status, location = resp.status, resp.getheader("Location")
        except (OSError, http.client.HTTPException) as exc:
            record("probe", target=f"{host}:{port}", ip=ip, reason=f"failed: {exc}")
            raise Denied(f"could not reach {host}: {exc}")
        finally:
            conn.close()
        record("probe", target=f"{host}:{port}", ip=ip, status=status)

        if status in REDIRECTS and location:
            url = urljoin(url, location)
            continue
        return hops
    raise Denied("too many redirects")


# --- CONNECT proxy ------------------------------------------------------------------

def split_target(target: str) -> tuple[str, int]:
    host, _, port = target.rpartition(":")
    if not host or not port.isdigit():
        raise Denied(f"bad CONNECT target {target[:200]!r}")
    return norm_host(host), int(port)


async def pipe(reader, writer, counter: list, idx: int) -> None:
    try:
        while data := await reader.read(65536):
            counter[idx] += len(data)
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def reply(writer, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
    try:
        await writer.drain()
    finally:
        writer.close()


async def handle_proxy(reader, writer) -> None:
    target = "?"
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
        method, target, _ = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ", 2)
        if method.upper() != "CONNECT":
            raise Denied(f"only CONNECT tunnels are allowed (got {method})")
        host, port = split_target(target)
        target = f"{host}:{port}"
        if target not in allowlist:
            raise Denied("not on the allowlist (not a link you added, or a redirect to a new host)")
        ips = await resolve(host, port)
    except Denied as exc:
        record("deny", target=target, reason=str(exc))
        return await reply(writer, "403 Forbidden")
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, asyncio.LimitOverrunError):
        record("deny", target=target, reason="malformed proxy request")
        return await reply(writer, "400 Bad Request")

    up_r = up_w = None
    for ip in ips:
        try:
            up_r, up_w = await asyncio.wait_for(asyncio.open_connection(ip, port), CONNECT_TIMEOUT)
            break
        except (OSError, asyncio.TimeoutError) as exc:
            record("error", target=target, ip=ip, reason=f"connect failed: {exc}")
    if up_w is None:
        return await reply(writer, "502 Bad Gateway")

    allowlist[target]["last_used"] = time.time()
    record("open", target=target, ip=ip)
    started = time.monotonic()
    writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await writer.drain()
    counter = [0, 0]  # bytes sent upstream, bytes received from upstream
    await asyncio.gather(pipe(reader, up_w, counter, 0), pipe(up_r, writer, counter, 1))
    record("close", target=target, ip=ip, bytes_out=counter[0], bytes_in=counter[1],
           secs=round(time.monotonic() - started, 1))


# --- control endpoint (api container only) --------------------------------------------

async def ctl_reply(writer, code: int, body: dict) -> None:
    data = json.dumps(body).encode()
    writer.write(f"HTTP/1.1 {code} X\r\nContent-Type: application/json\r\n"
                 f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data)
    await writer.drain()
    writer.close()


async def ctl_client_ok(writer) -> bool:
    peer = writer.get_extra_info("peername")[0]
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(CTL_CLIENT, None)
    except socket.gaierror:
        return False
    return peer in {i[4][0] for i in infos}


async def handle_ctl(reader, writer) -> None:
    if not await ctl_client_ok(writer):
        record("deny", target=f"control port from {writer.get_extra_info('peername')[0]}",
               reason=f"only {CTL_CLIENT} may use it")
        return await ctl_reply(writer, 403, {"ok": False, "error": "forbidden"})
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        lines = head.decode("latin-1").split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if l)}
        length = min(int(headers.get("content-length", "0")), 65536)
        body = json.loads(await reader.readexactly(length)) if length else {}
    except Exception:
        return await ctl_reply(writer, 400, {"ok": False, "error": "bad request"})

    route, _, query = path.partition("?")
    if method == "POST" and route == "/prepare":
        url = str(body.get("url", ""))
        try:
            hops = await asyncio.get_running_loop().run_in_executor(None, probe_chain, url)
        except Denied as exc:
            record("deny", url=url[:500], reason=str(exc))
            return await ctl_reply(writer, 200, {"ok": False, "error": str(exc)})
        for hop_url, host, port in hops:
            allow(host, port, hop_url[:500])
        save_allowlist()
        return await ctl_reply(writer, 200, {"ok": True, "hops": [h[0] for h in hops]})
    if method == "GET" and route == "/log":
        limit = int((parse_qs(query).get("limit") or ["500"])[0])
        return await ctl_reply(writer, 200, {"events": list(_recent)[-max(1, min(limit, 2000)):]})
    if method == "GET" and route == "/allowlist":
        return await ctl_reply(writer, 200, {"allowlist": allowlist})
    if method == "GET" and route == "/health":
        return await ctl_reply(writer, 200, {"ok": True})
    return await ctl_reply(writer, 404, {"ok": False, "error": "not found"})


async def housekeeping() -> None:
    while True:
        await asyncio.sleep(3600)
        expire_allowlist()
        save_allowlist()


async def main() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    setup_log()
    load_allowlist()
    proxy = await asyncio.start_server(handle_proxy, "0.0.0.0", PROXY_PORT)
    ctl = await asyncio.start_server(handle_ctl, "0.0.0.0", CTL_PORT)
    record("start", reason=f"allow_lan={ALLOW_LAN} internal={[str(n) for n in internal_subnets()]}")
    # As PID 1, SIGTERM is ignored unless handled: docker stop would hang.
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    tasks = [asyncio.create_task(t) for t in
             (proxy.serve_forever(), ctl.serve_forever(), housekeeping())]
    await stop.wait()
    for t in tasks:
        t.cancel()
    save_allowlist()
    record("stop")


if __name__ == "__main__":
    asyncio.run(main())
