import re
import time

from twisted.test.proto_helpers import StringTransportWithDisconnection
from twisted.test.proto_helpers import MemoryReactor
from twisted.python import failure
from twisted.internet.protocol import Factory
from twisted.internet.base import DelayedCall
from twisted.internet import error as terror
from twisted.internet.address import IPv4Address

from feat.common import defer
from feat.test import common
from feat.web import httpclient, http


class MockFactory(Factory):

    onConnectionMade_called = False
    onConnectionLost_called = False
    onConnectionReset_called = False

    def onConnectionMade(self, prot):
        self.onConnectionMade_called = True

    def onConnectionLost(self, prot, reason):
        self.onConnectionLost_called = True

    def onConnectionReset(self, prot):
        self.onConnectionReset_called = True


class ReactorMock(MemoryReactor):

    _connectors = None

    def connectTCP(self, host, port, factory, timeout=30, bindAddress=None):
        fc = super(ReactorMock, self).connectTCP(host, port, factory,
                                                 timeout, bindAddress)

        # define all the attributes a normal Connector would have defined
        fc.state = 'connecting'
        fc.timeout = timeout
        fc.host, fc.port = host, port
        fc.timeoutID = DelayedCall(time.time() + timeout, func=None,
                                   args=None, kw=None, cancel=None, reset=None)
        self.connectors.append(fc)
        return fc

    @property
    def connectors(self):
        if self._connectors is None:
            self._connectors = list()
        return self._connectors


class TestConnection(common.TestCase):

    def setUp(self):
        self.reactor = ReactorMock()
        self.connection = httpclient.Connection('testsite.com', 80,
                                                reactor=self.reactor)

    @defer.inlineCallbacks
    def testConnectAndCancel(self):
        d = self.connection.request(http.Methods.GET, '/')

        self.assertEqual(1, len(self.reactor.tcpClients))
        self.assertEqual('testsite.com', self.reactor.tcpClients[0][0])
        self.assertEqual(80, self.reactor.tcpClients[0][1])
        self.assertIsInstance(self.reactor.tcpClients[0][2],
                              httpclient.Factory)
        self.assertEqual(self.connection.connect_timeout,
                         self.reactor.tcpClients[0][3])

        d.cancel()
        self.assertFailure(d, defer.CancelledError)
        f = yield d
        exp = (r'Connection to testsite.com:80 was cancelled '
               '0.(\d+) seconds after it was initialized')
        self.assertTrue(re.match(exp, str(f)), (exp, str(f)))

    @defer.inlineCallbacks
    def testConnectTimeout(self):
        d = self.connection.request(http.Methods.GET, '/')
        factory = self.reactor.tcpClients[0][2]
        # this is what gets called when we time out connecting
        factory.clientConnectionFailed(
            self.reactor.connectors[0],
            failure.Failure(terror.TimeoutError()))
        self.assertFailure(d, terror.TimeoutError)
        f = yield d
        exp = ('User timeout caused connection failure: Timeout of 30'
               ' seconds expired while trying to connected to'
               ' testsite.com:80.')
        self.assertEqual(exp, str(f))

    @defer.inlineCallbacks
    def testCancelAfterConnected(self):
        d = self.connection.request(http.Methods.GET, '/')
        factory = self.reactor.tcpClients[0][2]

        addr = self.reactor.connectors[0]._address
        transport = self._make_connection(factory, addr)
        written = self.cb_after(None, transport, 'writeSequence')

        # wait for http client to write in the request line and headers
        yield written
        exp = 'GET / HTTP/1.1\r\nHost: testsite.com\r\n\r\n'

        v = transport.value()
        self.assertEqual(exp, v)

        # now cancel the request before receiving the response
        d.cancel()
        self.assertFailure(d, httpclient.RequestCancelled)
        f = yield d
        exp = (r'GET to http://10.0.0.1:12345/ was cancelled '
               '0.(\d+)s after it was sent.')
        self.assertTrue(re.match(exp, str(f)), str(f))

    @defer.inlineCallbacks
    def testSuccessfulGet(self):
        d = self.connection.request(http.Methods.GET, '/')
        factory = self.reactor.tcpClients[0][2]

        addr = self.reactor.connectors[0]._address
        transport = self._make_connection(factory, addr)
        yield self.cb_after(None, transport, 'writeSequence')

        transport.protocol.dataReceived(
            transport.protocol.delimiter.join([
                "HTTP/1.1 200 OK",
                "Content-Type: text/html",
                "Content-Length: 12",
                "",
                "This is body",
                ]))

        r = yield d
        self.assertIsInstance(r, httpclient.Response)
        self.assertEqual(200, r.status)
        self.addCleanup(self.connection.disconnect)

    @defer.inlineCallbacks
    def testTimeoutWaitingForFirstLine(self):
        d = self.connection.request(http.Methods.GET, '/')
        factory = self.reactor.tcpClients[0][2]

        addr = self.reactor.connectors[0]._address
        transport = self._make_connection(factory, addr)
        yield self.cb_after(None, transport, 'writeSequence')

        transport.protocol.process_timeout()
        self.assertFailure(d, httpclient.RequestTimeout)
        f = yield d
        exp = ('GET to http://10.0.0.1:12345/ failed '
               'because of timeout 0.(\d+)s after it was sent. '
               'When it happened it was waiting for the status line.')
        self.assertTrue(re.match(exp, str(f)), str(f))

    @defer.inlineCallbacks
    def testTimeoutWhileReceivingBody(self):
        d = self.connection.request(http.Methods.GET, '/')
        factory = self.reactor.tcpClients[0][2]

        addr = self.reactor.connectors[0]._address
        transport = self._make_connection(factory, addr)
        yield self.cb_after(None, transport, 'writeSequence')

        transport.protocol.dataReceived(
            transport.protocol.delimiter.join([
                "HTTP/1.1 200 OK",
                "Content-Type: text/html",
                "Content-Length: 12",
                "",
                ]))

        transport.protocol.process_timeout()
        self.assertFailure(d, httpclient.RequestTimeout)
        f = yield d
        exp = ('GET to http://10.0.0.1:12345/ failed '
               'because of timeout 0.(\d+)s after it was sent. '
               'When it happened it was receiving the headers.')
        self.assertTrue(re.match(exp, str(f)), str(f))

    def _make_connection(self, factory, addr):
        protocol = factory.buildProtocol(addr)
        transport = Transport()
        transport.protocol = protocol
        protocol.makeConnection(transport)
        return transport


class Transport(StringTransportWithDisconnection, object):

    pass


class TestProtocol(common.TestCase):

    def setUp(self):
        self.transport = StringTransportWithDisconnection()
        self.protocol = httpclient.Protocol(self, owner=None)
        self.protocol.factory = MockFactory()
        self.protocol.makeConnection(self.transport)
        self.transport.protocol = self.protocol

        self.addCleanup(self._disconnect_protocol)

    @defer.inlineCallbacks
    def testSimpleRequest(self):
        self.assertTrue(self.protocol.factory.onConnectionMade_called)
        self.assertTrue(self.protocol.is_idle())

        d = self.protocol.request(http.Methods.GET, '/',
                                  headers={'accept': 'text/html'})
        self.assertEqual('GET / HTTP/1.1\r\n'
                         'Accept: text/html\r\n\r\n', self.transport.value())

        self.assertFalse(self.protocol.is_idle())

        self.protocol.dataReceived(
            self.protocol.delimiter.join([
                "HTTP/1.1 200 OK",
                "Content-Type: text/html",
                "Content-Length: 12",
                "",
                "This is body",
                ]))
        response = yield d
        self.assertIsInstance(response, httpclient.Response)
        self.assertEqual(200, response.status)
        self.assertEqual({'content-type': 'text/html',
                          'content-length': '12'}, response.headers)
        self.assertEqual('This is body', response.body)
        self.assertTrue(self.protocol.is_idle())

        self.assertTrue(self.protocol.factory.onConnectionReset_called)

    @defer.inlineCallbacks
    def testCancelledRequest(self):
        d = self.protocol.request(http.Methods.GET, '/',
                                  headers={'accept': 'text/html'})
        d.cancel()

        self.assertFalse(self.transport.connected)
        self.assertFailure(d, httpclient.RequestCancelled)
        f = yield d
        exp = ('GET to http://10.0.0.1:12345/ was cancelled '
               '0.(\d+)s after it was sent.')
        self.assertTrue(re.match(exp, str(f)), str(f))

    def _disconnect_protocol(self):
        if self.transport.connected:
            self.transport.loseConnection()
        self.assertTrue(self.protocol.factory.onConnectionLost_called)
