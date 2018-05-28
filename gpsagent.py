#!/usr/bin/env python3

import argparse
import logging
import serial_asyncio
import os
import asyncio

class TruePositionState(object):
    def __init__(self, serial_proto):
        self._sats = {}
        self._wallclock = {}
        self._leap_seconds = {}
        self._active = False
        self._running = False
        self._msg_queue = asyncio.Queue(loop=asyncio.get_event_loop())
        self._serial_proto = serial_proto
        self._is_survey = False
        self._nr_sat_signals = 0
        self._tdop = 0.0
        self._temperature = 0.0
        self._geo = (0.0, 0.0)
        self._10mhz_bad = False
        self._1pps_bad = False
        self._antenna_bad = False
        self._holder_sec = 0
        self._nr_tracked_sats = 0
        self._state = -1
        self._have_version = False
        self._firmware_version = None
        self._firmware_serial = None
        self._is_active = False
        self._in_bootloader = False

    async def enqueue_message(self, msg):
        await self._msg_queue.put(msg)

    def _getver(self, msg):
        if 'BOOT' in msg:
            self._in_bootloader = True
            return '$PROCEED'

        fields = msg.split(' ')
        self._firmware_version = fields[1]
        self._firmware_serial = fields[6]

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
        self._sats[channel] = {
                'satId' : int(fields[2]),
                'elevation': int(fields[3]),
                'azimuth': int(fields[4]),
                'snr' : int(fields[5]),
            }

    def _wsat(self, msg):
        self._is_active = True
        pass

    def _default(self, msg):
        pass

    def _survey(self, msg):
        self._is_active = True
        pass

    def _extstatus(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        self._is_survey = int(fields[1]) == 1
        self._nr_sat_signals = int(fields[2])
        self._tdop = float(fields[3])
        self._temperature = float(fields[4])

    def _getpos(self, msg):
        self._is_active = True
        fields = msg.split(' ')
        lat = float(fields[1])/1e6
        lon = float(fields[2])/1e6
        elev = float(fields[3])
        msl_corr = int(fields[4])
        state = int(fields[5])

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
            logging.info('Tracking {} satellites'.format(nr_tracked_sats))

        if state != self._state:
            logging.info('State {} -> {}'.format(self._state, state))

        self._10mhz_bad = ten_mhz_bad
        self._1pps_bad = pps_bad
        self._antenna_bad = antenna_bad
        self._nr_tracked_sats = nr_tracked_sats
        self._state = state

    async def handle_messages(self):
        self._running = True

        logging.debug('Starting message handler')

        while (self._running):
            msg = await self._msg_queue.get()
            if (msg[0] != '$'):
                logging.debug('Invalid sentence: missing $: [{}]'.format(msg))
            if msg.startswith('$GETVER'):
                resp = self._getver(msg)
                if resp:
                    await self._serial_proto.enqueue_command(resp)
            elif msg.startswith('$CLOCK'):
                self._clock(msg)
            elif msg.startswith('$SAT'):
                self._sat(msg)
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
                logging.info('MSG: [{}]'.format(msg))
                self._default(msg)

            if self._in_bootloader:
                logging.info('Device is in bootloader, booting.')
                await self._serial_proto.enqueue_command('$PROCEED')
                self._in_bootloader = False

        logging.debug('Shutting down handling loop')

class TruePositionUART(asyncio.Protocol):
    def connection_made(self, transport):
        logging.debug('Connected to {}'.format(transport))
        self._transport = transport
        self._cur = ''
        self._messages = []
        self._cmd_queue = asyncio.Queue(asyncio.get_event_loop())
        self._running = False
        self._tpstate = None

    def set_trueposition_state(self, state):
        logging.debug('Setting TruePosition state to [{}]'.format(state))
        self._tpstate = state

    async def _send_queued_messages(self):
        self._running = True

        logging.debug('Starting TruePosition UART Protocol Sender')
        while self._running:
            msg = await self._cmd_queue.get()
            logging.debug('SEND: [{}]'.format(msg))
            self._transport.write(msg + '\r\n')
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

def main():
    parser = argparse.ArgumentParser(description='TruePosition GPSDO Management and NMEA Agent')
    parser.add_argument('-v', '--verbose', help='verbose output', action='store_true')
    parser.add_argument('-u', '--uart', help='specify the UART to use', required=True)
    parser.add_argument('-b', '--baud', type=int, help='specify the baud rate to use', required=True)
    parser.add_argument('outfifos', metavar='OUTFIFOS', help='Output FIFOs to write NMEA sentences to',
            nargs='+')
    args = parser.parse_args()

    loop = asyncio.get_event_loop()

    # Set verbosity, globally.
    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
        #loop.set_debug(True)

    logging.basicConfig(format='%(asctime)s - %(name)s:%(levelname)s:%(message)s', datefmt='%m/%d/%Y %H:%M:%S', level=log_level)

    logging.info('Starting GPS Agent (uart={}, baud rate={})'.format(args.uart, args.baud))

    coro = serial_asyncio.create_serial_connection(loop, TruePositionUART, args.uart, baudrate=args.baud)
    _, proto = loop.run_until_complete(coro)
    st = TruePositionState(proto)
    proto.set_trueposition_state(st)
    asyncio.ensure_future(st.handle_messages(), loop=loop)
    asyncio.ensure_future(proto._send_queued_messages(), loop=loop)

    logging.debug('Starting the event loop')
    loop.run_forever()
    logging.debug('We are out of here')
    loop.close()

if __name__ == '__main__':
    main()

