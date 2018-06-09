# TruePosition GPS Agent

The TruePosition GPS Agent is a work in progress application to create a simple
agent that will monitor the state of a TruePosition GPSDO.

GPS Agent is capable of outputing NMEA GPS updates on one or more FIFOs that can
be picked up from other applications. As well it has a basic status interface to
query the current status of the GPSDO (over http).

## Features

There is something resembling a feature set here.

 * Ephemeris can be logged in JSON form to a file (for later analysis)
 * The general state can be monitored from the logs output on stderr
 * NMEA sentences can be output to zero or more files/FIFOs/whatever for other
   apps to consume.
 * Time information can be output to a shared memory region to be picked up
   by ntpd or other compatible apps.

## Use Case

This could be used with a Raspberry Pi or similar SBC running Linux. The PPS
signal from the GPSDO could be fed into a GPIO on your SBC, and then ntpd can
consume the NMEA data and react to the PPS interrupt trigger.

## Requirements

This only is known to work with Python 3, but it might not be rocket science
to make it work with Python 2.7, I just haven't tried. Do yourself a favor
though, and switch to Python 3, if you find yourself considering the latter.

The `requirements.txt` file should be up to date, just install by piping it
into pip.

## License

The TruePosition GPS Agent is licensed under an MIT/X style license.

