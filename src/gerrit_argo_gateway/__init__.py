import asyncio
from contextlib import asynccontextmanager
import logging
import os
import re
import subprocess
import json

import asyncssh
import httpx


LOG = logging.getLogger(__name__)


class GerritGateway:
    # Regular expression for: "Support recheck to request re-running a test."
    # We only allow blanks or optionally a `sap-openstack-ci` before the `recheck` keyword
    # The text needs to either end after the `recheck` or at least have a whitespace
    # to allow for comments by the person triggering the recheck
    # Positive examples: (Ignoring the header "Patch Set \d:\n\n")
    #   recheck
    #   recheck - not sure why it failed
    #   sap-openstack-ci recheck
    # Negative examples:
    #   someotherci recheck
    #   rechecking
    _RECHECK_RE = re.compile(r"^.*\n(:?\s*sap-openstack-ci\s+)?\s*recheck(:?[\s]|$)", re.I)
    # Example: myuser@yourhost:1234
    _SSH_RE = re.compile(r"(?P<username>[^@]+)@(?P<host>[^:]+)(?::(?P<port>\d+))?")

    def __init__(self, subscriptions=None) -> None:
        self._subscriptions = subscriptions or []
        self._stop_loop = False
        self._process = None
        self._connection = None
        self._url = f"https://{os.getenv('ARGO_SERVER')}/api/v1/events/{os.getenv('ARGO_NAMESPACE')}/gerrit"
        if m := self._SSH_RE.search(os.getenv("GERRIT_SERVER", "")):
            self._ssh = m.groupdict()
        else:
            raise RuntimeError("GERRIT_SERVER needs to be set to `user@host`")
        if private := os.getenv("SSH_PRIVATE_KEY_PATH"):
            self._client_keys = [asyncssh.read_private_key(private)]
        else:
            self._client_keys = None

    def stop(self):
        self._stop_loop = True
        if self._process:
            try:
                self._process.terminate()
            except OSError:
                pass
        if self._connection:
            self._connection.close()

    async def _patchset_created(self, event):
        if event["patchSet"]["kind"] == "NO_CHANGE":
            LOG.debug(f"Rejecting {event['changeKey']['id']} due to patchSet.kind=NO_CHANGE")
            return
        return await self._trigger_build(event)

    async def _comment_added(self, event):
        try:
            comment = event["comment"]
            if not self._RECHECK_RE.match(comment):
                LOG.debug(f"Rejecting comment to {event['changeKey']['id']} not matching RE")
                return
            return await self._trigger_build(event)
        except KeyError:
            pass

    async def _trigger_build(self, event):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._url,
                headers={
                    "Authorization": os.getenv("ARGO_TOKEN"),
                    "Content-Type": "json",
                },
                json=event,
            )
            LOG.info(f"{event['type']}\t{event['project']}\t{event['changeKey']['id']}" f" -> {resp.status_code}")
            resp.raise_for_status()

    async def __call__(self) -> None:
        async for event in self._events():
            match event.get("type"):
                # See: https://review.opendev.org/Documentation/cmd-stream-events.html
                case "patchset-created":
                    await self._patchset_created(event)
                case "comment-added":
                    await self._comment_added(event)
            await asyncio.sleep(0.1)

    async def _events(self):
        async with self._stream_event() as process:
            while not self._stop_loop and not process.stdout.at_eof():
                async for event in process.stdout:
                    yield json.loads(event)

    @asynccontextmanager
    async def _connect(self):
        async with asyncssh.connect(
            self._ssh["host"],
            port=int(self._ssh.get("port", 22)),
            username=self._ssh["username"],
            client_keys=self._client_keys,
        ) as conn:
            self._connection = conn
            yield conn

    @asynccontextmanager
    async def _stream_event(self):
        async with self._connect() as conn:
            cmd = ["gerrit", "stream-events"]
            if self._subscriptions:
                for s in self._subscriptions:
                    cmd.extend(["-s", s])
            async with conn.create_process(" ".join(cmd), stderr=subprocess.STDOUT) as process:
                self._process = process
                yield process
