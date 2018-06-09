# Copyright (c) 2018 Phil Vachon <phil@security-embedded.com>
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import asyncio
import logging
import ntpdshm
import time

class TruePositionSHMWriter(object):
    def __init__(self, loop=asyncio.get_event_loop(), unit=0):
        self._msg_queue = asyncio.Queue(loop=loop)
        logging.debug('Connecting to shared memory segment, unit {}'.format(unit))
        self._shm = ntpdshm.NtpdShm(unit=unit)
        self._shm.mode = 1
        self._shm.precision = -7
        self._shm.leap = 0

    async def enqueue_tp_message(self, msg):
        await self._msg_queue.put(msg)

    async def _writer(self):
        while self._running:
            msg = await self._msg_queue.get()

            msg_type = msg.get('type', 'unknown')
            if msg_type == 'sat':
                pass
            elif msg_type == 'gps':
                self._shm.update(msg.get('time', None))
            else:
                logging.debug('Unknown message type: {} (Message: {})'.format(msg_type, msg))

    def start(self, loop=asyncio.get_event_loop()):
        self._running = True
        asyncio.ensure_future(self._writer(), loop=loop)

    def stop(self):
        self._running = False

