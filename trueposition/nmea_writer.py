# Copyright (c) 2018 Phil Vachon <phil@security-embedded.com>
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import aiofiles
import asyncio
import logging

class TruePositionNMEAWriter(object):
    def __init__(self, out_file, loop=asyncio.get_event_loop()):
        self._msg_queue = asyncio.Queue(loop=loop)
        self._file = loop.run_until_complete(aiofiles.open(out_file, 'wt'))

    async def enqueue_tp_message(self, msg):
        await self._msg_queue.put(msg)

    def __format_gps(self, msg):
        def _frac_to_dm(frac_n):
            frac = abs(frac_n)
            deg = int(frac)
            mins = (frac - deg) * 60.0
            return (deg, mins)

        lon = msg.get('longitude', 0)
        lat = msg.get('latitude', 0)
        lat_deg, lat_mins = _frac_to_dm(lat)
        lon_deg, lon_mins = _frac_to_dm(lon)
        fields = {'time': msg.get('time'),
                'elev': msg.get('elevMetres', 0),
                'to_geoid': msg.get('geoidOffs', 0),
                'lat_deg': lat_deg,
                'lat_mins': lat_mins,
                'lon_deg': lon_deg,
                'lon_mins': lon_mins,
                'lat_dir': 'N' if lat > 0 else 'S',
                'lon_dir': 'E' if lon > 0 else 'W',
                'fix_quality': '1' if msg.get('goodFix', False) else 0,
                'nr_sats': msg.get('nrSats', 0),
                }

        return 'GPGGA,{time},{lat_deg:02d}{lat_mins:6.4f},{lat_dir},{lon_deg:03d}{lon_mins:6.4f},{lon_dir},{fix_quality},{nr_sats},,{elev},M,{to_geoid},M,,,'.format(**fields)

    async def _writer(self):
        def __nmea_chksum(msg):
            checksum = 0
            for c in msg:
                checksum ^= ord(c)
            return checksum

        while self._running:
            msg = await self._msg_queue.get()
            msg_type = msg.get('type', 'unknown')
            if msg_type == 'sat':
                pass
            elif msg_type == 'gps':
                msg = self.__format_gps(msg)
                await self._file.write('${}*{:2x}\n'.format(msg, __nmea_chksum(msg)))
                await self._file.flush()
            else:
                logging.debug('Unknown message type: {} (Message: {})'.format(msg_type, msg))

    def start(self, loop=asyncio.get_event_loop()):
        self._running = True
        asyncio.ensure_future(self._writer(), loop=loop)

    def stop(self):
        self._running = False

