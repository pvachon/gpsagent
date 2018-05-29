#!/usr/bin/env python3

import argparse
import logging
import serial_asyncio
import os
import asyncio
import aiofiles
import time
import json
from aiohttp import web

class TruePositionState(object):
    def __init__(self, serial_proto, outputs=[]):
        self._sats = {}
        self._wallclock = {}
        self._leap_seconds = {}
        self._quality = 9
        self._active = False
        self._running = False
        self._msg_queue = asyncio.Queue(loop=asyncio.get_event_loop())
        self._serial_proto = serial_proto
        self._is_survey = False
        self._nr_sat_signals = 0
        self._tdop = 0.0
        self._temperature = 0.0
        self._geo = (0.0, 0.0)
        self._elev = 0
        self._elev_corr = 0
        self._10mhz_bad = False
        self._1pps_bad = False
        self._antenna_bad = False
        self._holdover_sec = 0
        self._nr_tracked_sats = 0
        self._state = -1
        self._have_version = False
        self._firmware_version = None
        self._firmware_serial = None
        self._is_active = False
        self._in_bootloader = False
        self._outputs = outputs
        self._survey_secs = 0

    def _encode_state(self):
        state = {'gpsEpoch': self._wallclock,
                 'leapSeconds': self._leap_seconds,
                 'timeQuality' : self._quality,
                 'isBooted' : self._is_active,
                 'isSurvey' : self._is_survey,
                 'extParams' : {'nrSignals': self._nr_sat_signals,
                                'tdop' : self._tdop,
                                'temperatureC' : self._temperature},
                 'location' : {'lat': self._geo[0],
                               'lon': self._geo[1],
                               'elevMetres': self._elev,
                               'elevCorrWGS84': self._elev_corr},
                 'tenMhzBad' : self._10mhz_bad,
                 'onePPSBad' : self._1pps_bad,
                 'antennaBad' : self._antenna_bad,
                 'holdoverSec' : self._holdover_sec,
                 'trackedSats' : [y for y in self._sats.values()],
                 'nrTrackedSats' : self._nr_tracked_sats,
                 'state' : self._state,
                 'firmwareVersion' : self._firmware_version,
                 'firmwareSerial' : self._firmware_serial,}

        if self._is_survey:
            state['surveySeconds'] = self._survey_secs
        return state

    def get_state(self):
        return self._encode_state()

    @property
    def epoch_time(self):
        kGPS_EPOCH_DELTA = 315964800 + self._leap_seconds
        return kGPS_EPOCH_DELTA + self._wallclock

    def _encode_gps_state(self):
        return {'time': time.strftime('%H%M%S', time.gmtime(self.epoch_time)),
                'nrTrackedSats': self._nr_tracked_sats,
                'elevMetres': self._elev,
                'latitude': self._geo[0],
                'longitude': self._geo[1],
                'geoidOffs': self._elev_corr,
                'goodFix': self._state == 0,
                'nrSats': self._nr_tracked_sats,
                }

    def get_gps_state(self):
        return self._encode_gps_state()

    async def enqueue_message(self, msg):
        """
        Helper function to enqueue a message to be consumed by the TruePosition state
        manager.
        """
        await self._msg_queue.put(msg)

    def _getver(self, msg):
        if 'BOOT' in msg:
            self._in_bootloader = True
            self._is_active = False
            return

        logging.debug('GETVER: [{}]'.format(msg))
        fields = msg.split(' ')
        self._firmware_version = fields[1]
        self._firmware_serial = fields[6]
        self._is_active = True

    def _clock(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        self._wallclock = int(fields[1])
        self._leap_seconds = int(fields[2])
        self._quality = int(fields[3])

    def _sat(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        channel = int(fields[1])

        sat_info = {'satId': int(fields[2]),
                    'el': int(fields[3]),
                    'az': int(fields[4]),
                    'snr' : int(fields[5]),
                    'lastSeen' : self.epoch_time,
                    'slotId': channel,}
        self._sats[channel] = sat_info
        return sat_info

    def _wsat(self, msg):
        self._is_active = True

    def _default(self, msg):
        logging.info('UNKNOWN MSG: [{}]'.format(msg))

    def _survey(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        lat = float(fields[1])/1e6
        lon = float(fields[2])/1e6
        self._elev = float(fields[3])
        self._elev_corr = float(fields[4])
        self._survey_secs = int(fields[5])
        self._geo = (lat, lon)


    def _extstatus(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        is_survey = int(fields[1]) == 1
        nr_sat_signals = int(fields[2])
        self._tdop = float(fields[3])
        self._temperature = float(fields[4])

        if is_survey != self._is_survey:
            if is_survey:
                logging.info('GPS Receiver is performing a site survey')

        if nr_sat_signals != self._nr_sat_signals:
            logging.info('We see {} external satellite signals'.format(nr_sat_signals))

        self._is_survey = is_survey
        self._nr_sat_signals = nr_sat_signals

    def _getpos(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        lat = float(fields[1])/1e6
        lon = float(fields[2])/1e6
        self._elev = float(fields[3])
        self._elev_corr = float(fields[4])
        state = int(fields[5])
        self._geo = (lat, lon)

    def _status(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        ten_mhz_bad = int(fields[1]) != 0
        pps_bad = int(fields[2]) != 0
        antenna_bad = int(fields[3]) != 0
        self._holdover_sec = int(fields[4])
        nr_tracked_sats = int(fields[5])
        state = int(fields[6])

        # Catch various state changes
        if ten_mhz_bad != self._10mhz_bad:
            if ten_mhz_bad:
                logging.info('10MHz Precision Timing Signal is bad!')
            else:
                logging.info('10MHz Precision Timing Signal is good.')

        if pps_bad != self._1pps_bad:
            if pps_bad:
                logging.info('1PPS signal is bad!')
            else:
                logging.info('1PPS signal has come back')

        if antenna_bad != self._antenna_bad:
            if antenna_bad:
                logging.info('Antenna is bad.')
            else:
                logging.info('Antenna is good.')

        if nr_tracked_sats != self._nr_tracked_sats:
            logging.info('Software PLL locked for {} satellites'.format(nr_tracked_sats))

        if state != self._state:
            logging.info('State {} -> {}'.format(self._state, state))

        self._10mhz_bad = ten_mhz_bad
        self._1pps_bad = pps_bad
        self._antenna_bad = antenna_bad
        self._nr_tracked_sats = nr_tracked_sats
        self._state = state

    async def _request_location_update(self):
        logging.debug('Starting location request update tracker')
        while self._running:
            await asyncio.sleep(30)
            if self._is_active:
                # Send a GETPOS command to update our internal view of the position
                await self._serial_proto.enqueue_command('$GETPOS')

    async def _handle_messages(self):
        """
        Private async function that acts as a green thread that consumes messages and updates
        the state of the TruePosition.
        """
        logging.debug('Starting TruePosition message handler')
        while self._running:
            msg = await self._msg_queue.get()
            if (msg[0] != '$'):
                logging.debug('Invalid sentence: missing $: [{}]'.format(msg))
            if msg.startswith('$GETVER'):
                resp = self._getver(msg)
                if resp:
                    await self._serial_proto.enqueue_command(resp)
            elif msg.startswith('$CLOCK'):
                self._clock(msg)
                # A clock message needs to be converted to an NMEA sentence
                clock_state = self.get_gps_state()
                clock_state['type'] = 'gps'
                for o in self._outputs:
                    await o.enqueue_tp_message(clock_state)
            elif msg.startswith('$SAT'):
                sat_info = self._sat(msg)
                # Send out the updated satellite data
                sat_info['type'] = 'sat'
                for o in self._outputs:
                    await o.enqueue_tp_message(sat_info)

            elif msg.startswith('$WSAT'):
                self._wsat(msg)
            elif msg.startswith('$SURVEY'):
                self._survey(msg)
            elif msg.startswith('$EXTSTATUS'):
                self._extstatus(msg)
            elif msg.startswith('$GETPOS'):
                self._getpos(msg)
            elif msg.startswith('$STATUS'):
                self._status(msg)
            else:
                self._default(msg)

            if self._in_bootloader:
                logging.info('Device is in bootloader, booting.')
                await self._serial_proto.enqueue_command('$PROCEED')
                self._in_bootloader = False
            if self._is_active and (not self._firmware_serial or not self._firmware_version):
                logging.debug('Querying for the firmware version')
                await self._serial_proto.enqueue_command('$GETVER')

        logging.debug('Shutting down handling loop')

    def start(self, loop=asyncio.get_event_loop()):
        self._running = True
        asyncio.ensure_future(self._handle_messages(), loop=loop)
        asyncio.ensure_future(self._request_location_update(), loop=loop)
        logging.debug('Done startup of TruePosition state tracker')

    def stop(self):
        self._running = False

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

        return 'GPGGA,{time},{lat_deg}{lat_mins:6.4f},{lat_dir},{lon_deg:03d}{lon_mins:6.4f},{lon_dir},{fix_quality},{nr_sats},,{elev},M,{to_geoid},M,,,'.format(**fields)

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

class TruePositionUART(asyncio.Protocol):
    def connection_made(self, transport):
        logging.debug('Connected to {}'.format(transport))
        self._transport = transport
        self._cur = ''
        self._messages = []
        self._cmd_queue = asyncio.Queue(loop=asyncio.get_event_loop())
        self._running = False
        self._tpstate = None

    def set_trueposition_state(self, state):
        logging.debug('Setting TruePosition state to [{}]'.format(state))
        self._tpstate = state

    async def _send_queued_messages(self):
        """
        Green thread for sending queued messages to the device, from the TruePosition
        state manager.
        """
        logging.debug('Starting TruePosition UART Protocol Sender')
        while self._running:
            msg = await self._cmd_queue.get()
            logging.debug('SEND: [{}]'.format(msg))
            self._transport.write(bytearray(msg + '\r\n', 'utf-8'))
            await asyncio.sleep(1.0)

    async def enqueue_command(self, msg):
        await self._cmd_queue.put(msg)

    def data_received(self, data):
        for c in data.decode('utf-8'):
            if c == '\r':
                self._messages.append(self._cur)
                self._cur = ''
            elif c == '\n':
                # Eat \n, due to weird bootloader bugs
                continue
            else:
                self._cur += c

        if self._messages:
            for message in self._messages:
                if message.strip():
                    asyncio.ensure_future(self._tpstate.enqueue_message(message.strip()))
            self._messages = []

    def connection_lost(self, exc):
        logging.debug('Connection lost to {}. Reason: {}'.format(self._transport, exc))
        asyncio.get_event_loop().stop()

    def start(self, tpstate, loop=asyncio.get_event_loop()):
        self._running = True
        self.set_trueposition_state(tpstate)
        asyncio.ensure_future(self._send_queued_messages(), loop=loop)

    def stop(self):
        self._running = False

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

def main():
    parser = argparse.ArgumentParser(description='TruePosition GPSDO Management and NMEA Agent')
    parser.add_argument('-v', '--verbose', help='verbose output', action='store_true')
    parser.add_argument('-u', '--uart', help='specify the UART to use', required=True)
    parser.add_argument('-b', '--baud', type=int, help='specify the baud rate to use', required=True)
    parser.add_argument('-P', '--port', type=int,
            help='specify the TCP port for the HTTP server to listen on', required=False, default=24601)
    parser.add_argument('-s', '--satfile', help='specify output file to dump satellite ephemeris to',
            required = False)
    parser.add_argument('outfifos', metavar='OUTFIFOS', help='Output FIFOs to write NMEA sentences to',
            nargs='+')
    args = parser.parse_args()

    loop = asyncio.get_event_loop()

    # Set verbosity, globally.
    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
        #loop.set_debug(True)

    logging.basicConfig(format='%(asctime)s - %(name)s:%(levelname)s:%(message)s',
            datefmt='%m/%d/%Y %H:%M:%S', level=log_level)

    logging.info('Starting GPS Agent (uart={}, baud rate={})'.format(args.uart, args.baud))

    # Set up the asyncio serial protocol
    coro = serial_asyncio.create_serial_connection(loop, TruePositionUART, args.uart, baudrate=args.baud)
    _, proto = loop.run_until_complete(coro)

    # For each output fifo, create an output object
    outputs = [ TruePositionNMEAWriter(outfifo) for outfifo in args.outfifos ]

    # Create the TruePosition state manager
    st = TruePositionState(proto, outputs)

    # Start the HTTP server
    logging.info('Starting HTTP Command and Control server on port {}'.format(args.port))
    tphttp = TruePositionHTTPApi(st, port=args.port, loop=loop)
    tphttp.start(loop=loop)

    # Check if the user asked to log satellite ephemeris data
    if args.satfile:
        logging.info('Dumping satellite ephemeris to file {}'.format(args.satfile))
        outputs.append(TruePositionSatWriter(args.satfile, loop=loop))

    # Start this mess
    for output in outputs:
        output.start(loop=loop)
    proto.start(st, loop=loop)
    st.start(loop=loop)

    logging.debug('Starting the event loop')
    loop.run_forever()
    logging.debug('We are out of here')
    loop.close()

if __name__ == '__main__':
    main()

