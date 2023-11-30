# ruff: noqa: D104
import asyncio
import json
import logging
import os
import re
import subprocess
import typing
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import asyncssh
import httpx

LOG = logging.getLogger(__name__)

JSONType = dict[str, typing.Any]  # Not really correct, but it will do


class GerritGateway:
    """
    Listens to gerrit stream events and pushes them to the argo event api.

    The configuration is mostly by environment variables as described in the README.md.
    """

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

    def __init__(self, subscriptions: list[str] | None = None) -> None:
        """
        Set up the gateway for gerrit stream events filtered by subscriptions (or all if unset).

        :param subscriptions: A list of the desired subscriptions. For details see:
            https://gerrit-review.googlesource.com/Documentation/cmd-stream-events.html
        """
        self._subscriptions = subscriptions or []
        self._stop_loop = False
        self._process = None
        self._connection = None
        self._url = f"https://{os.getenv('ARGO_SERVER')}/api/v1/events/{os.getenv('ARGO_NAMESPACE')}/gerrit"

        if m := self._SSH_RE.search(os.getenv("GERRIT_SERVER", "")):
            self._ssh = m.groupdict()
        else:
            msg = "GERRIT_SERVER needs to be set to `user@host`"
            raise RuntimeError(msg)

        if private := os.getenv("SSH_PRIVATE_KEY_PATH"):
            self._client_keys = [asyncssh.read_private_key(private)]
        else:
            self._client_keys = []

    def stop(self) -> None:
        """Stop listening to events and close the connection."""
        self._stop_loop = True
        if self._process:
            with suppress(OSError):
                self._process.terminate()
        if self._connection:
            self._connection.close()

    async def _patchset_created(self, event: JSONType) -> None:
        if event["patchSet"]["kind"] == "NO_CHANGE":
            LOG.debug("Rejecting %s due to patchSet.kind=NO_CHANGE", event["changeKey"]["id"])
            return
        await self._trigger_build(event)

    async def _comment_added(self, event: JSONType) -> None:
        try:
            comment = event["comment"]
            if not self._RECHECK_RE.match(comment):
                LOG.debug("Rejecting comment to %s not matching RE", event["changeKey"]["id"])
                return
            await self._trigger_build(event)
        except KeyError:
            pass

    async def _trigger_build(self, event: JSONType) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._url,
                headers={
                    "Authorization": os.getenv("ARGO_TOKEN"),
                    "Content-Type": "json",
                },
                json=event,
            )
            LOG.info("%s\t%s\t%s -> %s", event["type"], event["project"], event["changeKey"]["id"], resp.status_code)
            resp.raise_for_status()

    async def __call__(self) -> None:
        """Run the stream loop and only stop if either the connection drops or is closed via `stop()`."""
        async for event in self._events():
            match event.get("type"):
                # See: https://review.opendev.org/Documentation/cmd-stream-events.html
                case "patchset-created":
                    await self._patchset_created(event)
                case "comment-added":
                    await self._comment_added(event)
            await asyncio.sleep(0.1)

    async def _events(self) -> AsyncIterator[JSONType]:
        async with self._stream_event() as process:
            while not self._stop_loop and not process.stdout.at_eof():
                async for event in process.stdout:
                    yield json.loads(event)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[asyncssh.SSHClientConnection]:
        async with asyncssh.connect(
            self._ssh["host"],
            port=int(self._ssh.get("port", 22)),
            username=self._ssh["username"],
            client_keys=self._client_keys,
        ) as conn:
            self._connection = conn
            yield conn

    @asynccontextmanager
    async def _stream_event(self) -> AsyncIterator[asyncssh.SSHClientProcess]:
        async with self._connect() as conn:
            cmd = ["gerrit", "stream-events"]
            if self._subscriptions:
                for s in self._subscriptions:
                    cmd.extend(["-s", s])
            async with conn.create_process(" ".join(cmd), stderr=subprocess.STDOUT) as process:
                self._process = process
                yield process
