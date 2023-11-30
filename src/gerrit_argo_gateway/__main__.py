"""
Main module to be invoked via python -m gerrit_argo_gateway.

Sets up logging and the gateway and hooks up the signal handlers to stop the thread.
"""
import asyncio
import logging
import signal

from . import GerritGateway


async def _main() -> None:
    gateway = GerritGateway(subscriptions=["patchset-created", "comment-added"])
    loop = asyncio.get_running_loop()

    def stop(*args, **kwargs) -> None:  # noqa: ARG001
        gateway.stop()

    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, stop)

    await gateway()


logging.basicConfig(level=logging.INFO)
asyncio.run(_main())
