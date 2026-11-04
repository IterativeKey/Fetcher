"""Fetcher API server: REST + live WebSocket over aria2, with a job history.

Auth is mandatory: every /api request must carry FETCHER_API_TOKEN in the
`X-Fetcher-Token` header (optionally prefixed with `token:`). WebSocket
clients send it as their first message instead, so it never lands in a URL
(and therefore never in access logs). The one exception is /api/files: a
browser download can't send headers, so it uses a short-lived link signed
with the token (the token itself is never in the URL).

aria2 does the downloading; the job history (db.py) is what the UI shows and
what decides which files on the share may be served or deleted (files.py).
"""

import asyncio
import hashlib
import hmac
import mimetypes
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, files
from .aria2_client import FINISHED, Aria2Client, Aria2Error
from .db import DB

if not config.FETCHER_API_TOKEN:
    raise SystemExit("FETCHER_API_TOKEN must be set (openssl rand -hex 16)")

# Plain HTTP(S) file transfers only. Peer-to-peer (magnet/torrent) and
# metalink are refused: they make aria2 contact hosts other than the one you
# asked for. FTP is refused because its data connections go to whatever
# address the server announces, which the egress allowlist can't vet.
ALLOWED_SCHEMES = {"http", "https"}
REFUSED_SUFFIXES = (".torrent", ".metalink", ".meta4")
MAX_URL_LEN = 8192
MAX_BATCH = 500

# Browser download links open these inline (view in a tab); everything else
# is always a download. Every file response is also served with a sandbox CSP
# so nothing from the share can ever run script on this origin.
INLINE_PREFIXES = ("image/", "video/", "audio/", "text/plain")
INLINE_REFUSED = {"image/svg+xml"}

ACTIVE = {"active", "waiting", "paused"}

client = Aria2Client()
egress = httpx.AsyncClient(base_url=config.EGRESS_URL, timeout=120)
db = DB()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sockets = set()
    pulse = asyncio.create_task(_pulse(app))
    yield
    pulse.cancel()
    await client.aclose()
    await egress.aclose()


app = FastAPI(
    title="Fetcher",
    version="0.3.0",
    lifespan=lifespan,
    # No /docs, /redoc or /openapi.json: they're unauthenticated and the docs
    # pages load Swagger/ReDoc from third-party CDNs.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    # FastAPI's built-in OpenTelemetry hooks: nothing is exported without an
    # SDK installed, but keep them off explicitly.
    telemetry={"tracing": False, "metrics": False, "logs": False,
               "operation_spans": False, "auto_configure": False},
)


# --- auth & validation -------------------------------------------------------

def token_ok(provided: str) -> bool:
    if provided.startswith("token:"):
        provided = provided[len("token:"):]
    return bool(provided) and secrets.compare_digest(provided, config.FETCHER_API_TOKEN)


def auth(request: Request) -> None:
    if not token_ok(request.headers.get("x-fetcher-token", "")):
        raise HTTPException(401, "invalid or missing token")


def check_url(url: str) -> str:
    url = url.strip()
    if not url or len(url) > MAX_URL_LEN or any(c.isspace() or ord(c) < 32 for c in url):
        raise HTTPException(400, "not a valid URL")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme == "magnet":
        raise HTTPException(400, "magnet links are not supported")
    if scheme not in ALLOWED_SCHEMES or not parts.hostname:
        raise HTTPException(400, "only http:// and https:// links are supported")
    if parts.path.lower().endswith(REFUSED_SUFFIXES):
        raise HTTPException(400, "torrent and metalink files are not supported")
    return url


def job_or_404(job_id: int) -> dict:
    job = db.get(job_id)
    if not job:
        raise HTTPException(404, "no such download")
    return job


def refused(exc: Exception, job: dict | None = None) -> HTTPException:
    if job and "no longer on disk" in str(exc):
        db.update(job["id"], file_deleted=1)
    return HTTPException(409, str(exc))


def sign(job_id: int, exp: int, inline: int) -> str:
    msg = f"{job_id}:{exp}:{inline}".encode()
    return hmac.new(config.FETCHER_API_TOKEN.encode(), msg, hashlib.sha256).hexdigest()


# --- core actions (shared by single and bulk endpoints) ---------------------

async def prepare(url: str) -> None:
    # The gateway follows the redirect chain and allows each hop's host;
    # aria2 can reach nothing else.
    try:
        prep = (await egress.post("/prepare", json={"url": url})).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"egress gateway unreachable: {exc}")
    if not prep.get("ok"):
        raise HTTPException(400, prep.get("error", "link refused by egress gateway"))


def options_for(category: str, paused: bool, speed_limit: int, out: str = "") -> dict:
    try:
        opts = {"dir": files.category_dir(category)}
        if out:
            opts["out"] = files.check_name(out)
    except files.FileRefused as exc:
        raise HTTPException(400, str(exc))
    if paused:
        opts["pause"] = "true"
    if speed_limit:
        opts["max-download-limit"] = str(speed_limit)
    return opts


async def start(url: str, category: str, paused: bool) -> int:
    url = check_url(url)
    opts = options_for(category, paused, 0)
    await prepare(url)
    try:
        gid = await client.add(url, opts)
    except Aria2Error as exc:
        raise HTTPException(400, str(exc))
    return db.add(url, category, gid, "paused" if paused else "waiting")


async def act(job: dict, action: str) -> None:
    gid = job["gid"]
    try:
        if action == "pause":
            if job["status"] in ("active", "waiting") and gid:
                await client.pause(gid)
        elif action == "resume":
            if job["status"] == "paused" and gid:
                await client.unpause(gid)
        elif action in ("top", "bottom"):
            if job["status"] in ("waiting", "paused") and gid:
                await client.move(gid, action)
        elif action == "stop":
            if job["status"] in ACTIVE and gid:
                await client.stop(gid)
                db.update(job["id"], status="stopped", gid=None, **progress(job))
        elif action == "retry":
            await retry(job)
        elif action == "favorite":
            db.update(job["id"], favorite=1)
        elif action == "unfavorite":
            db.update(job["id"], favorite=0)
        elif action == "hide":
            db.update(job["id"], hidden=1)
        elif action == "unhide":
            db.update(job["id"], hidden=0)
        elif action == "delete-file":
            await delete_file(job)
        elif action == "remove":
            await remove(job, with_file=False)
        elif action == "remove-and-delete":
            await remove(job, with_file=True)
        else:
            raise HTTPException(400, f"unknown action: {action}")
    except Aria2Error as exc:
        raise HTTPException(409, str(exc))


async def retry(job: dict) -> None:
    if job["status"] == "complete":
        # "Download again": a new entry; the old file and history stay.
        await start(job["url"], job["category"], False)
        return
    if job["status"] in ACTIVE:
        return
    await prepare(job["url"])
    out = ""
    # Resume our own partial file (aria2 picks it up via its .aria2 file);
    # only if it is still the file we were writing.
    if job["path"]:
        try:
            files.verified(job)
            out = os.path.basename(job["path"])
        except files.FileRefused:
            out = ""
    opts = options_for(job["category"], False, job["speed_limit"], out)
    try:
        gid = await client.add(job["url"], opts)
    except Aria2Error as exc:
        raise HTTPException(400, str(exc))
    fields = dict(gid=gid, status="waiting", error="", finished_at=None)
    if not out:
        fields.update(path="", file_dev=None, file_ino=None, file_size=None,
                      file_mtime=None, file_deleted=0)
    db.update(job["id"], **fields)


def progress(job: dict) -> dict:
    """The last progress aria2 reported, so a stopped job keeps it."""
    l = live.get(job["id"])
    return {"done": l["done"], "total": l["total"] or job["total"]} if l else {}


async def delete_file(job: dict) -> None:
    if job["status"] in ACTIVE and job["gid"]:
        await client.stop(job["gid"])
        db.update(job["id"], status="stopped", gid=None, **progress(job))
    try:
        if job["status"] == "complete":
            files.delete(job)
        else:
            files.delete_partial(job)
    except files.FileRefused as exc:
        if "no longer on disk" not in str(exc):  # already gone: that's the goal
            raise refused(exc, job)
    except OSError as exc:
        raise HTTPException(500, f"could not delete: {exc.strerror}")
    db.update(job["id"], file_deleted=1)


async def remove(job: dict, with_file: bool) -> None:
    if with_file and not job["file_deleted"]:
        await delete_file(job)
    elif job["gid"]:
        await client.stop(job["gid"])
    db.delete(job["id"])


# --- REST ----------------------------------------------------------------------

class NewDownloads(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    category: str = ""
    paused: bool = False


class JobPatch(BaseModel):
    favorite: bool | None = None
    hidden: bool | None = None
    speed_limit: int | None = Field(default=None, ge=0)


class Rename(BaseModel):
    name: str


Action = Literal["pause", "resume", "stop", "retry", "top", "bottom", "favorite",
                 "unfavorite", "hide", "unhide", "delete-file", "remove",
                 "remove-and-delete"]


class Bulk(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)
    action: Action


class Settings(BaseModel):
    speed_limit: int = Field(ge=0)               # bytes/s, 0 = unlimited
    max_concurrent: int = Field(ge=1, le=20)


@app.get("/api/health")
async def health(request: Request):
    auth(request)
    try:
        return {"ok": True, "aria2_version": await client.version()}
    except Exception as exc:
        raise HTTPException(503, f"aria2 unreachable: {exc}")


@app.get("/api/state")
async def state(request: Request):
    auth(request)
    return full_snapshot()


@app.post("/api/downloads")
async def add_downloads(body: NewDownloads, request: Request):
    auth(request)
    results = []
    for url in dict.fromkeys(u.strip() for u in body.urls if u.strip()):
        try:
            results.append({"url": url, "ok": True,
                            "id": await start(url, body.category.strip(), body.paused)})
        except HTTPException as exc:
            results.append({"url": url, "ok": False, "error": exc.detail})
    return {"results": results}


@app.patch("/api/downloads/{job_id}")
async def patch_download(job_id: int, body: JobPatch, request: Request):
    auth(request)
    job = job_or_404(job_id)
    fields = {}
    if body.favorite is not None:
        fields["favorite"] = int(body.favorite)
    if body.hidden is not None:
        fields["hidden"] = int(body.hidden)
    if body.speed_limit is not None:
        fields["speed_limit"] = body.speed_limit
        if job["gid"] and job["status"] in ACTIVE:
            try:
                await client.change_option(job["gid"], {"max-download-limit": str(body.speed_limit)})
            except Aria2Error as exc:
                raise HTTPException(409, str(exc))
    db.update(job_id, **fields)
    return {"ok": True}


@app.post("/api/downloads/{job_id}/rename")
async def rename_download(job_id: int, body: Rename, request: Request):
    auth(request)
    job = job_or_404(job_id)
    if job["status"] != "complete":
        raise HTTPException(409, "only finished downloads can be renamed")
    try:
        path = files.rename(job, body.name)
    except files.FileRefused as exc:
        raise refused(exc, job)
    except OSError as exc:
        raise HTTPException(500, f"could not rename: {exc.strerror}")
    ident = files.identity(path)  # rename keeps inode/size/mtime; re-read anyway
    fields = dict(path=path, name=os.path.basename(path))
    if ident:
        fields.update(file_dev=ident[0], file_ino=ident[1], file_size=ident[2], file_mtime=ident[3])
    db.update(job_id, **fields)
    return {"ok": True, "name": os.path.basename(path)}


@app.post("/api/downloads/{job_id}/checksum")
async def checksum(job_id: int, request: Request):
    auth(request)
    job = job_or_404(job_id)
    if job["status"] != "complete":
        raise HTTPException(409, "only finished downloads can be checked")
    try:
        digest = await asyncio.to_thread(files.sha256, job)
    except files.FileRefused as exc:
        raise refused(exc, job)
    db.update(job_id, sha256=digest)
    return {"sha256": digest}


@app.post("/api/downloads/{job_id}/link")
async def file_link(job_id: int, request: Request, inline: bool = False):
    """A short-lived URL the browser can open to download (or view) the file."""
    auth(request)
    job = job_or_404(job_id)
    if job["status"] != "complete" or job["file_deleted"]:
        raise HTTPException(409, "the file isn't available")
    try:
        files.verified(job, finished=True)
    except files.FileRefused as exc:
        raise refused(exc, job)
    exp = int(time.time()) + config.LINK_TTL
    flag = int(inline)
    return {"url": f"api/files/{job_id}?exp={exp}&inline={flag}&sig={sign(job_id, exp, flag)}"}


@app.get("/api/files/{job_id}")
async def serve_file(job_id: int, exp: int, sig: str, inline: int = 0):
    if exp < time.time() or not secrets.compare_digest(sig, sign(job_id, exp, int(bool(inline)))):
        raise HTTPException(403, "link expired or invalid - start the download again from Fetcher")
    job = job_or_404(job_id)
    try:
        path = files.verified(job, finished=True)
    except files.FileRefused as exc:
        raise refused(exc, job)
    media = mimetypes.guess_type(path)[0] or "application/octet-stream"
    show = bool(inline) and media.startswith(INLINE_PREFIXES) and media not in INLINE_REFUSED
    if not show:
        media = "application/octet-stream"
    return FileResponse(
        path, media_type=media, filename=os.path.basename(path),
        content_disposition_type="inline" if show else "attachment",
        headers={"Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; media-src 'self'",
                 "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"})


@app.post("/api/downloads/{job_id}/{action}")
async def job_action(job_id: int, action: Action, request: Request):
    auth(request)
    await act(job_or_404(job_id), action)
    return {"ok": True}


@app.delete("/api/downloads/{job_id}")
async def delete_download(job_id: int, request: Request, delete_file: bool = False):
    auth(request)
    await act(job_or_404(job_id), "remove-and-delete" if delete_file else "remove")
    return {"ok": True}


@app.post("/api/bulk")
async def bulk(body: Bulk, request: Request):
    auth(request)
    errors = []
    for job_id in body.ids:
        job = db.get(job_id)
        if not job:
            continue
        try:
            await act(job, body.action)
        except HTTPException as exc:
            errors.append({"id": job_id, "name": job["name"] or job["url"], "error": exc.detail})
    return {"ok": not errors, "errors": errors}


@app.post("/api/global/{action}")
async def global_action(action: Literal["pause", "resume"], request: Request):
    auth(request)
    try:
        await (client.pause_all() if action == "pause" else client.unpause_all())
    except Aria2Error as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


def current_settings() -> dict:
    return {"speed_limit": int(db.get_setting("speed_limit", "0")),
            "max_concurrent": int(db.get_setting(
                "max_concurrent", os.getenv("MAX_CONCURRENT_DOWNLOADS", "5")))}


@app.get("/api/settings")
async def get_settings(request: Request):
    auth(request)
    return current_settings()


@app.put("/api/settings")
async def put_settings(body: Settings, request: Request):
    auth(request)
    db.set_setting("speed_limit", str(body.speed_limit))
    db.set_setting("max_concurrent", str(body.max_concurrent))
    await apply_settings(force=True)
    return current_settings()


@app.get("/api/connections")
async def connections(request: Request, limit: int = 500):
    """Every connection the download engine attempted, from the gateway's log."""
    auth(request)
    try:
        return (await egress.get("/log", params={"limit": limit})).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"egress gateway unreachable: {exc}")


# --- sync loop: aria2 -> history, then push to the UI -----------------------

live: dict[int, dict] = {}       # job id -> {speed, connections, done, total}
engine_ok = False


async def apply_settings(force: bool = False) -> None:
    want = current_settings()
    want = {"max-overall-download-limit": str(want["speed_limit"]),
            "max-concurrent-downloads": str(want["max_concurrent"])}
    try:
        if not force:
            have = await client.global_options()
            if all(have.get(k) == v for k, v in want.items()):
                return
        await client.change_global(want)
    except (Aria2Error, httpx.HTTPError):
        pass


def _name(j: dict) -> tuple[str, str, str]:
    f = (j.get("files") or [{}])[0]
    path = f.get("path") or ""
    uris = f.get("uris") or []
    url = uris[0]["uri"] if uris else ""
    name = os.path.basename(path) or os.path.basename(urlsplit(url).path) or ""
    return path, name, url


async def sync() -> None:
    """Fold aria2's view into the history. Rows are read BEFORE asking aria2,
    so a job added in between is never mistaken for one aria2 lost."""
    global live, engine_ok
    rows = db.by_gid()
    try:
        snap = await client.list()
        engine_ok = True
    except (Aria2Error, httpx.HTTPError):
        engine_ok = False
        live = {}
        return
    seen, new_live = set(), {}
    for j in snap["active"] + snap["waiting"] + snap["stopped"]:
        gid = j["gid"]
        seen.add(gid)
        path, name, url = _name(j)
        status = "stopped" if j["status"] == "removed" else j["status"]
        row = rows.get(gid)
        if row is None:
            # Started outside this API (or before the history existed): adopt it.
            rel = os.path.relpath(j.get("dir") or config.DOWNLOAD_DIR, config.DOWNLOAD_DIR)
            category = "" if rel.startswith(".") else rel
            db.add(url or f"gid:{gid}", category, gid, status)
            row = db.by_gid().get(gid)
            if row is None:
                continue
        total, done = int(j["totalLength"]), int(j["completedLength"])
        fields = {}
        if row["status"] != status:
            fields.update(status=status, done=done)
        if path and row["path"] != path:
            fields["path"] = path
        if name and row["name"] != name:
            fields["name"] = name
        if total and row["total"] != total:
            fields["total"] = total
        if (j.get("errorMessage") or "") != row["error"]:
            fields["error"] = j.get("errorMessage") or ""
        p = path or row["path"]
        if p and row["file_ino"] is None:
            ident = files.identity(p)
            if ident:
                fields.update(file_dev=ident[0], file_ino=ident[1])
        if j["status"] in FINISHED:
            if status == "complete":
                ident = files.identity(p)
                fields.update(done=total, finished_at=time.time())
                if ident:
                    fields.update(file_dev=ident[0], file_ino=ident[1],
                                  file_size=ident[2], file_mtime=ident[3])
            fields["gid"] = None  # the history owns it now
        db.update(row["id"], **fields)
        if j["status"] in FINISHED:
            await client.forget(gid)
        else:
            new_live[row["id"]] = {"status": status, "speed": int(j["downloadSpeed"]),
                                   "connections": int(j.get("connections") or 0),
                                   "done": done, "total": total}
    for gid, row in rows.items():
        if gid not in seen and row["status"] in ACTIVE:
            db.update(row["id"], gid=None, status="error",
                      error="The download engine lost this job (restarted?). Retry resumes it.")
    live = new_live


def stats() -> dict:
    return {"speed": sum(v["speed"] for v in live.values()),
            "active": sum(1 for v in live.values() if v["status"] == "active"),
            "disk": files.disk(), "engine": engine_ok}


def full_snapshot() -> dict:
    return {"type": "full", "version": db.version, "jobs": db.all(), "live": live,
            "categories": db.categories(), "settings": current_settings(), "stats": stats()}


async def _pulse(app: FastAPI):
    sent_version, tick = 0, 0
    while True:
        try:
            await sync()
            if engine_ok and tick % 10 == 0:
                await apply_settings()
            if app.state.sockets:
                if db.version != sent_version:
                    msg = full_snapshot()
                    sent_version = msg["version"]
                else:
                    msg = {"type": "live", "live": live, "stats": stats()}
                for ws in list(app.state.sockets):
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        app.state.sockets.discard(ws)
        except Exception as exc:  # never let the loop die
            print(f"sync error: {exc!r}", flush=True)
        tick += 1
        await asyncio.sleep(1)


@app.websocket("/api/events")
async def events(ws: WebSocket):
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_text(), timeout=10)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await ws.close(code=4401)
        return
    if not token_ok(first):
        await ws.close(code=4401)
        return
    await ws.send_json(full_snapshot())
    app.state.sockets.add(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive pings from the UI
    except WebSocketDisconnect:
        pass
    finally:
        app.state.sockets.discard(ws)


# --- Static UI last, so /api routes win ----------------------------------

app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
