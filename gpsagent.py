import argparse
import logging
import serial

class TruePositionUART(object):
    def __init__(self):
        pass

def main():
    parser = argparse.ArgumentParser(description='TruePosition GPSDO Management and NMEA Agent')
    parser.add_argument('-v', '--verbose', help='verbose output', action='store_true')
    parser.add_argument('-u', '--uart', help='specify the UART to use', mandatory=True)
    parser.add_argument('-b', '--baud', type=int, help='specify the baud rate to use', mandatory=True)
    parser.add_argument('outfifos', metavar='OUTFIFOS', help='Output FIFOs to write NMEA sentences to', nargs='+')
    args = parser.parse_args()

    # Set verbosity, globally.
    if args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(format='%(asctime)s - %(name)s:%(levelname)s:%(message)s', datefmt='%m/%d/%Y %H:%M:%S', level=log_level)


if __name__ == '__main__':
    main()

