# Copyright (c) 2018 Phil Vachon <phil@security-embedded.com>
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import asyncio
import logging

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
        return {'time': self.epoch_time,
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

