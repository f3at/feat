from twisted.test.proto_helpers import StringTransportWithDisconnection
from twisted.internet.protocol import Factory

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


class TestProtocol(common.TestCase):

    def setUp(self):
        self.transport = StringTransportWithDisconnection()
        self.transport.addr = ('testsite.com', 80)
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
        exp = 'GET to http://testsite.com:80/ was cancelled by the user 0.000s after it was sent.'
        self.assertEqual(exp, str(f))

    def _disconnect_protocol(self):
        if self.transport.connected:
            self.transport.loseConnection()
        self.assertTrue(self.protocol.factory.onConnectionLost_called)
