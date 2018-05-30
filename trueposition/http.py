import logging
import asyncio
import json
from aiohttp import web

class TruePositionHTTPApi(object):
    def __init__(self, tpstate, port=24601, loop=asyncio.get_event_loop()):
        self._tpstate = tpstate
        self._app = web.Application()
        self._app.add_routes([web.get('/', self.get)])
        self._runner = web.AppRunner(self._app)
        loop.run_until_complete(self._runner.setup())
        self._site = web.TCPSite(self._runner, 'localhost', port)

    async def get(self, request):
        return web.json_response(self._tpstate.get_state())

    def start(self, loop):
        # Start the site
        asyncio.ensure_future(self._site.start())

    def stop(self):
        pass

