# -*- Mode: Python -*-
# -*- coding: UTF-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.test import common

from feat.common import defer, serialization
from feat.web import http, tunnel


class DummyDispatcher(object):

    implements(tunnel.ITunnelDispatcher)

    def __init__(self):
        self.reset()

    def reset(self):
        self.messages = []

    ### tunnel.ITunnelDispatcher ###

    def dispatch(self, uri, data):
        self.messages.append((uri, data))


class Versioned(serialization.Serializable, serialization.VersionAdapter):

    __metaclass__ = type("MetaAv1", (type(serialization.Serializable),
                                     type(serialization.VersionAdapter)), {})


class Av1(Versioned):
    type_name = "A"

    def __init__(self):
        self.foo = "42"

    def __repr__(self):
        return "<Av1 foo=%r>" % (self.foo, )


class Av2(Av1):
    type_name = "A"

    def __init__(self):
        self.bar = 42

    def __repr__(self):
        return "<Av2 bar=%r>" % (self.bar, )

    @staticmethod
    def upgrade_to_2(snapshot):
        snapshot["bar"] = int(snapshot["foo"])
        del snapshot["foo"]
        return snapshot

    @staticmethod
    def downgrade_to_1(snapshot):
        snapshot["foo"] = str(snapshot["bar"])
        del snapshot["bar"]
        return snapshot


@common.attr(timescale=0.1)
class TestHTTPTunnel(common.TestCase):

    def setUp(self):
        port_range = range(4000, 4100)
        r1 = serialization.get_registry().clone()
        r1.register(Av1)
        self.d1 = DummyDispatcher()
        self.t1 = tunnel.Tunnel(self, port_range, self.d1, "localhost",
                                version=1, registry=r1, max_delay=10)
        r2 = serialization.get_registry().clone()
        r2.register(Av2)
        self.d2 = DummyDispatcher()
        self.t2 = tunnel.Tunnel(self, port_range, self.d2, "localhost",
                                version=2, registry=r2, max_delay=10)
        return common.TestCase.setUp(self)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.t1.stop_listening()
        yield self.t2.stop_listening()
        yield self.t1.disconnect()
        yield self.t2.disconnect()
        yield common.TestCase.tearDown(self)

    @defer.inlineCallbacks
    def testSimpleCleanup(self):
        yield self.t1.start_listening()
        yield self.t2.start_listening()

    @defer.inlineCallbacks
    def testSimple(self):
        yield self.t1.start_listening()
        yield self.t2.start_listening()

        url1a = http.append_location(self.t1.uri, "spam")
        url2a = http.append_location(self.t2.uri, "beans")

        yield self.t1.post(url2a, "tomato")
        yield self.wait_for_idle(20)
        self.assertEqual(self.d2.messages, [(url2a, "tomato")])

        yield self.t2.post(url1a, "sausage")
        yield self.wait_for_idle(20)
        self.assertEqual(self.d1.messages, [(url1a, "sausage")])

        yield self.wait_for_idle(20)

    @defer.inlineCallbacks
    def testPipeline(self):
        yield self.t1.start_listening()
        yield self.t2.start_listening()

        url1a = http.append_location(self.t1.uri, "spam")
        url2a = http.append_location(self.t2.uri, "beans")
        url1b = http.append_location(self.t1.uri, "bacon")
        url2b = http.append_location(self.t2.uri, "egg")

        self.t1.post(url2a, 1)
        self.t2.post(url1a, 2)
        self.t2.post(url1b, 3)
        self.t1.post(url2b, 4)
        self.t1.post(url2a, 5)
        self.t1.post(url2b, 6)
        self.t2.post(url1a, 7)
        self.t2.post(url1a, 8)
        self.t1.post(url2b, 9)

        yield self.wait_for_idle(20)

        self.assertEqual(self.d1.messages, [(url1a, 2), (url1b, 3),
                                            (url1a, 7), (url1a, 8)])
        self.assertEqual(self.d2.messages, [(url2a, 1), (url2b, 4),
                                            (url2a, 5), (url2b, 6),
                                            (url2b, 9)])

        yield self.wait_for_idle(20)

    @defer.inlineCallbacks
    def testSerialization(self):
        yield self.t1.start_listening()
        yield self.t2.start_listening()

        url1 = http.append_location(self.t1.uri, "spam")
        url2 = http.append_location(self.t2.uri, "beans")

        a1a = Av1()
        a1a.foo = "78"
        a1b = Av1()
        a1b.foo = "88"

        yield self.t1.post(url2, a1a)
        yield self.t1.post(url2, a1b)

        self.assertEqual(len(self.d2.messages), 2)
        _url, msg1 = self.d2.messages[0]
        _url, msg2 = self.d2.messages[1]
        self.assertTrue(isinstance(msg1, Av2))
        self.assertTrue(isinstance(msg2, Av2))
        self.assertFalse(hasattr(msg1, "foo"))
        self.assertFalse(hasattr(msg2, "foo"))
        self.assertTrue(hasattr(msg1, "bar"))
        self.assertTrue(hasattr(msg2, "bar"))
        self.assertEqual(msg1.bar, 78)
        self.assertEqual(msg2.bar, 88)

        msg1.bar = 66
        msg2.bar = 33

        yield self.t2.post(url1, msg1)
        yield self.t2.post(url1, msg2)

        self.assertEqual(len(self.d1.messages), 2)
        _url, msg1 = self.d1.messages[0]
        _url, msg2 = self.d1.messages[1]
        self.assertTrue(isinstance(msg1, Av1))
        self.assertTrue(isinstance(msg2, Av1))
        self.assertTrue(hasattr(msg1, "foo"))
        self.assertTrue(hasattr(msg2, "foo"))
        self.assertFalse(hasattr(msg1, "bar"))
        self.assertFalse(hasattr(msg2, "bar"))
        self.assertEqual(msg1.foo, "66")
        self.assertEqual(msg2.foo, "33")

        yield self.wait_for_idle(20)

    @defer.inlineCallbacks
    def testRetries(self):
        yield self.t1.start_listening()
        yield self.t2.start_listening()

        url = http.append_location(self.t2.uri, "spam")

        yield self.t1.post(url, 1)
        self.assertEqual(self.d2.messages, [(url, 1)])
        self.d2.reset()

        yield self.wait_for_idle(20)

        yield self.t2.disconnect()
        yield self.t2.stop_listening()

        d = self.t1.post(url, 2)

        yield common.delay(None, 10)

        self.assertEqual(self.d2.messages, [])

        yield self.t2.start_listening()

        yield d
        self.assertEqual(self.d2.messages, [(url, 2)])
        self.d2.reset()

        yield self.t2.stop_listening()
        yield self.t2.disconnect()

        self.t1.post(url, 1)
        self.t1.post(url, 2)
        self.t1.post(url, 3)
        self.t1.post(url, 4)
        self.t1.post(url, 5)

        yield common.delay(None, 10)

        self.assertEqual(self.d2.messages, [])

        yield self.t2.start_listening()
        yield self.wait_for_idle(20)

        self.assertEqual(self.d2.messages, [(url, 1), (url, 2), (url, 3),
                                            (url, 4), (url, 5)])

        yield self.wait_for_idle(20)

    @defer.inlineCallbacks
    def testExpiration(self):
        yield self.t1.start_listening()
        yield self.t2.start_listening()

        url = http.append_location(self.t2.uri, "spam")

        yield self.t2.stop_listening()

        result = yield self.t1.post(url, 1, 2)

        self.assertFalse(result)
        self.assertEqual(self.d2.messages, [])

        yield self.t2.start_listening()

        result = yield self.t1.post(url, 2, 20)

        self.assertTrue(result)
        self.assertEqual(self.d2.messages, [(url, 2)])

    @defer.inlineCallbacks
    def testIdleConnections(self):
        self.t1.request_timeout = 10
        self.t1.response_timeout = 11
        self.t2.request_timeout = 10
        self.t2.response_timeout = 11

        yield self.t1.start_listening()
        yield self.t2.start_listening()

        url1 = http.append_location(self.t1.uri, "spam")
        url2 = http.append_location(self.t2.uri, "bacon")

        self.assertEqual(self.t1.get_peers(), [])
        self.assertEqual(self.t2.get_peers(), [])

        result = yield self.t1.post(url2, 1)
        self.assertTrue(result)

        self.assertEqual(self.t1.get_peers(), [self.t2.uri])
        self.assertEqual(self.t2.get_peers(), [])

        yield common.delay(None, 6)

        self.assertEqual(self.t1.get_peers(), [self.t2.uri])
        self.assertEqual(self.t2.get_peers(), [])

        result = yield self.t2.post(url1, 2)
        self.assertTrue(result)

        self.assertEqual(self.t1.get_peers(), [self.t2.uri])
        self.assertEqual(self.t2.get_peers(), [self.t1.uri])

        yield common.delay(None, 6)

        self.assertEqual(self.t1.get_peers(), [])
        self.assertEqual(self.t2.get_peers(), [self.t1.uri])

        yield common.delay(None, 6)

        self.assertEqual(self.t1.get_peers(), [])
        self.assertEqual(self.t2.get_peers(), [])

        self.d1.reset()
        self.d2.reset()

        self.t1.post(url2, 1)
        self.t2.post(url1, 2)

        yield self.wait_for_idle(20)

        self.assertEqual(self.t1.get_peers(), [self.t2.uri])
        self.assertEqual(self.t2.get_peers(), [self.t1.uri])
        self.assertEqual(self.d1.messages, [(url1, 2)])
        self.assertEqual(self.d2.messages, [(url2, 1)])

    def wait_for_idle(self, timeout):

        def check():
            return self.t1.is_idle() and self.t2.is_idle()

        return self.wait_for(check, timeout)
