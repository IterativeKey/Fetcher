"""Tiny async JSON-RPC client for aria2."""

import httpx

from . import config

# Fields the API needs; "files" carries the file path and source URI.
JOB_KEYS = ["gid", "status", "totalLength", "completedLength",
            "downloadSpeed", "connections", "dir", "files", "errorCode", "errorMessage"]

# Statuses aria2 keeps only as a result record (remove via removeDownloadResult).
FINISHED = {"complete", "error", "removed"}


class Aria2Error(Exception):
    pass


class Aria2Client:
    def __init__(self):
        self._http = httpx.AsyncClient(timeout=10)

    def _params(self, extra: list | None) -> list:
        head = [f"token:{config.ARIA2_RPC_SECRET}"] if config.ARIA2_RPC_SECRET else []
        return head + (extra or [])

    async def call(self, method: str, extra: list | None = None):
        return await self._post(method, self._params(extra))

    async def _post(self, method: str, params: list):
        body = {"jsonrpc": "2.0", "id": "fetcher", "method": method, "params": params}
        resp = await self._http.post(config.ARIA2_RPC_URL, json=body)
        # aria2 reports RPC errors as HTTP 400 with a JSON-RPC error body;
        # read that before falling back to the HTTP status.
        try:
            payload = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise Aria2Error(f"{method}: non-JSON response")
        if "error" in payload:
            raise Aria2Error(payload["error"].get("message", method))
        resp.raise_for_status()
        return payload["result"]

    # --- convenience wrappers -------------------------------------------

    async def version(self) -> str:
        return (await self.call("aria2.getVersion"))["version"]

    async def add(self, url: str, options: dict[str, str]) -> str:
        """Start one download. `options` is built by the API from validated
        values only (dir under the share, out=a known file name, pause,
        speed limit) - never passed through from clients, since options like
        dir/out/allow-overwrite could otherwise write anywhere aria2 can."""
        return await self.call("aria2.addUri", [[url], options])

    async def list(self) -> dict:
        """All jobs in ONE request, so aria2 answers from a single moment.
        (Three separate calls could miss a job that moved from waiting to
        active in between, and the API would then think aria2 lost it.)"""
        calls = [{"methodName": m, "params": self._params(p)} for m, p in (
            ("aria2.tellActive", [JOB_KEYS]),
            ("aria2.tellWaiting", [0, 1000, JOB_KEYS]),
            ("aria2.tellStopped", [0, 1000, JOB_KEYS]))]
        try:
            results = await self._post("system.multicall", [calls])
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError):
            # A pooled keep-alive connection aria2 already closed: a read-only
            # call, so one retry on a fresh connection is safe. (Not on a
            # timeout: that would only double the wait.)
            results = await self._post("system.multicall", [calls])
        out = []
        for r in results:
            if isinstance(r, dict):  # per-call fault: {"code", "message"}
                raise Aria2Error(r.get("message", "system.multicall"))
            out.append(r[0])
        active, waiting, stopped = out
        return {"active": active, "waiting": waiting, "stopped": stopped}

    async def status(self, gid: str) -> str:
        return (await self.call("aria2.tellStatus", [gid, ["status"]]))["status"]

    async def stop(self, gid: str) -> None:
        """Stop a job (if running) and drop aria2's record of it. Files stay."""
        try:
            status = await self.status(gid)
        except Aria2Error:
            return  # aria2 doesn't know it any more: nothing to stop
        if status not in FINISHED:
            await self.call("aria2.forceRemove", [gid])
        try:
            await self.call("aria2.removeDownloadResult", [gid])
        except Aria2Error:
            pass  # forceRemove is async; the sync loop clears the result later

    async def forget(self, gid: str) -> None:
        try:
            await self.call("aria2.removeDownloadResult", [gid])
        except Aria2Error:
            pass

    async def pause(self, gid: str) -> None:
        await self.call("aria2.forcePause", [gid])

    async def unpause(self, gid: str) -> None:
        await self.call("aria2.unpause", [gid])

    async def pause_all(self) -> None:
        await self.call("aria2.forcePauseAll")

    async def unpause_all(self) -> None:
        await self.call("aria2.unpauseAll")

    async def move(self, gid: str, where: str) -> None:
        pos, how = (0, "POS_SET") if where == "top" else (0, "POS_END")
        await self.call("aria2.changePosition", [gid, pos, how])

    async def change_option(self, gid: str, options: dict[str, str]) -> None:
        await self.call("aria2.changeOption", [gid, options])

    async def global_options(self) -> dict:
        return await self.call("aria2.getGlobalOption")

    async def change_global(self, options: dict[str, str]) -> None:
        await self.call("aria2.changeGlobalOption", [options])

    async def aclose(self) -> None:
        await self._http.aclose()
