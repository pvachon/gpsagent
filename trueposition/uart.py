import asyncio
import logging
import serial_asyncio

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

    @staticmethod
    def Create(loop=asyncio.get_event_loop(), uart='/dev/ttyUSB0', baudrate=9600):
        coro = serial_asyncio.create_serial_connection(loop, TruePositionUART, uart, baudrate=baudrate)
        _, proto = loop.run_until_complete(coro)
        return proto


