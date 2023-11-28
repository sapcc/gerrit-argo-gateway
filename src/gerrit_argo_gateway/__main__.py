import asyncio
import logging
import signal

from . import GerritGateway

async def main():
    gateway = GerritGateway(subscriptions=["patchset-created", "comment-added"])
    loop = asyncio.get_running_loop()

    def stop(*args, **kwargs):
        gateway.stop()

    for sig in [signal.SIGINT, signal.SIGTERM]:
        # signal.signal(sig, stop)
        loop.add_signal_handler(sig, stop)

    await gateway()


logging.basicConfig(level=logging.INFO)
asyncio.run(main())
