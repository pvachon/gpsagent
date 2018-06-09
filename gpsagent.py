#!/usr/bin/env python3

# Copyright (c) 2018 Phil Vachon <phil@security-embedded.com>
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import argparse
import logging
import asyncio

import trueposition

def main():
    parser = argparse.ArgumentParser(description='TruePosition GPSDO Management and NMEA Agent')
    parser.add_argument('-v', '--verbose', help='verbose output', action='store_true')
    parser.add_argument('-u', '--uart', help='specify the UART to use', required=True)
    parser.add_argument('-b', '--baud', type=int, help='specify the baud rate to use', required=True)
    parser.add_argument('-P', '--port', type=int,
            help='specify the TCP port for the HTTP server to listen on', required=False, default=24601)
    parser.add_argument('-s', '--satfile', help='specify output file to dump satellite ephemeris to',
            required=False)
    parser.add_argument('-S', '--shm-unit', help='update specified shared memory unit for ntpd', required=False,
            default=0, type=int)
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
    proto = trueposition.TruePositionUART.Create(loop=loop, uart=args.uart, baudrate=args.baud)

    # For each output fifo, create an output object
    outputs = [ trueposition.TruePositionNMEAWriter(outfifo) for outfifo in args.outfifos ]

    # Create the TruePosition state manager
    st = trueposition.TruePositionState(proto, outputs)

    # Start the HTTP server
    logging.info('Starting HTTP Command and Control server on port {}'.format(args.port))
    tphttp = trueposition.TruePositionHTTPApi(st, port=args.port, loop=loop)
    tphttp.start(loop=loop)

    # Check if the user asked to log satellite ephemeris data
    if args.satfile:
        logging.info('Dumping satellite ephemeris to file {}'.format(args.satfile))
        outputs.append(trueposition.TruePositionSatWriter(args.satfile, loop=loop))

    if args.shm_unit:
        logging.info('Time will be populated in shm unit {}'.format(args.shm_unit))
        outputs.append(trueposition.TruePositionSHMWriter(loop=loop, unit=args.shm_unit))

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

