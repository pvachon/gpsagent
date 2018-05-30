# Copyright (c) 2018 Phil Vachon <phil@security-embedded.com>
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import aiofiles
import asyncio
import logging
import json

class TruePositionSatWriter(object):
    def __init__(self, out_file, loop=asyncio.get_event_loop()):
        self._msg_queue = asyncio.Queue(loop=loop)
        self._file = loop.run_until_complete(aiofiles.open(out_file, 'wt+'))

    async def enqueue_tp_message(self, msg):
        await self._msg_queue.put(msg)

    async def _writer(self):
        while self._running:
            msg = await self._msg_queue.get()
            if msg.get('type', 'unknown') == 'sat':
                logging.debug('EPHEMERIS: {}'.format(msg))
                await self._file.write(json.dumps(msg) + '\n')
                await self._file.flush()

    def start(self, loop=asyncio.get_event_loop()):
        self._running = True
        asyncio.ensure_future(self._writer(), loop=loop)

    def stop(self):
        self._running = False

