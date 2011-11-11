# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import reactor

from feat.common import defer, time

from . import common


def delay_raise(error_factory, delay):

    def raise_error(_param):
        raise error_factory()

    d = defer.Deferred()
    d.addCallback(raise_error)
    time.call_later(delay, d.callback, None)
    return d


class TestDeferUtils(common.TestCase):

    @defer.inlineCallbacks
    def testJoin(self):
        res = yield defer.join(common.delay(0, 0.01),
                               common.delay(1, 0.01),
                               common.delay(2, 0.01))
        self.assertEqual(res, [0, 1, 2])

        res = yield defer.join(delay_raise(ValueError, 0.01),
                               delay_raise(ValueError, 0.01),
                               delay_raise(ValueError, 0.01))
        self.assertEqual(res, [])

        res = yield defer.join(common.delay(0, 0.01),
                               delay_raise(ValueError, 0.01),
                               common.delay(2, 0.01))
        self.assertEqual(res, [0, 2])

        res = yield defer.join(1, 2, 3)
        self.assertEqual(res, [1, 2, 3])

        res = yield defer.join(1, common.delay(2, 0.1), 3)
        self.assertEqual(res, [1, 2, 3])


class TestNotifier(common.TestCase):

    def testSimpleCallback(self):

        def check(result, expected, name, counters):
            self.assertEqual(result, expected)
            counters[name] = counters.get(name, 0) + 1

        def fail(failure):
            self.fail("Unexpected failure: %s" % failure.getErrorMessage())

        counters = {}

        n = defer.Notifier()

        d = n.wait("foo")
        d.addCallback(check, "FOO", "foo", counters)
        d.addErrback(fail)

        d = n.wait("bar")
        d.addCallback(check, "BAR", "bar", counters)
        d.addErrback(fail)

        d = n.wait("foo")
        d.addCallback(check, "FOO", "foo", counters)
        d.addErrback(fail)

        d = n.wait("barr")
        d.addCallback(check, "BARR", "barr", counters)
        d.addErrback(fail)

        self.assertEqual(counters, {})

        n.callback("foo", "FOO")
        self.assertEqual(counters["foo"], 2)

        n.callback("bar", "BAR")
        self.assertEqual(counters["bar"], 1)

        n.callback("barr", "BARR")
        self.assertEqual(counters["barr"], 1)

        # Unknwon notification should not fail

        n.callback("dummy", "DUMMY")
        self.assertFalse("dummy" in counters)

        # If called a second time nothing more should be called

        n.callback("foo", "FOO")
        self.assertEqual(counters["foo"], 2)

        n.callback("bar", "BAR")
        self.assertEqual(counters["bar"], 1)

        n.callback("barr", "BARR")
        self.assertEqual(counters["barr"], 1)

    def testSimpleErrback(self):

        def check(failure, expected, name, counters):
            self.assertTrue(failure.check(expected))
            counters[name] = counters.get(name, 0) + 1

        def fail(result):
            self.fail("Unexpected result: %s" % result)

        counters = {}

        n = defer.Notifier()

        d = n.wait("foo")
        d.addCallback(fail)
        d.addErrback(check, ValueError, "foo", counters)

        d = n.wait("bar")
        d.addCallback(fail)
        d.addErrback(check, TypeError, "bar", counters)

        d = n.wait("foo")
        d.addCallback(fail)
        d.addErrback(check, ValueError, "foo", counters)

        d = n.wait("barr")
        d.addCallback(fail)
        d.addErrback(check, Exception, "barr", counters)

        self.assertEqual(counters, {})

        n.errback("foo", ValueError())
        self.assertEqual(counters["foo"], 2)

        n.errback("bar", TypeError())
        self.assertEqual(counters["bar"], 1)

        n.errback("barr", Exception())
        self.assertEqual(counters["barr"], 1)

        # Unknwon notification should not fail

        n.callback("dummy", RuntimeError())
        self.assertFalse("dummy" in counters)

        # If called a second time nothing more should be called

        n.errback("foo", ValueError())
        self.assertEqual(counters["foo"], 2)

        n.errback("bar", TypeError())
        self.assertEqual(counters["bar"], 1)

        n.errback("barr", Exception())
        self.assertEqual(counters["barr"], 1)

    @common.attr(timeout=1)
    @defer.inlineCallbacks
    def testCancellingWaitEvent(self):
        n = defer.Notifier()
        d = n.wait('some_event')
        self.assertFailure(d, defer.CancelledError)
        reactor.callLater(0.02, d.cancel)
        yield d

        n.callback('some_event', 1) #doesn't cause as deferred is removed


class Canceller(object):

    def __init__(self):
        self.called = False

    def cancel(self, d):
        self.called = True


class SpecialError(Exception):
    pass


class TestTimeout(common.TestCase):

    @defer.inlineCallbacks
    def testItTimeoutsCorrectly(self):
        canceller = Canceller()
        master = defer.Deferred(canceller.cancel)
        timeout = defer.Timeout(0.02, master)
        self.assertFalse(timeout.called)
        self.assertFailure(timeout, defer.TimeoutError)
        yield common.delay(None, 0.03)
        self.assertTrue(canceller.called)

    @defer.inlineCallbacks
    def testCallbackInTime(self):
        canceller = Canceller()
        master = defer.Deferred(canceller.cancel)
        timeout = defer.Timeout(0.02, master)
        self.assertFalse(timeout.called)
        yield common.delay(None, 0.01)
        self.assertFalse(timeout.called)
        self.assertFalse(master.called)
        master.callback("result")
        res = yield timeout
        self.assertEqual('result', res)
        self.assertFalse(canceller.called)

    @defer.inlineCallbacks
    def testErrbackInTime(self):
        canceller = Canceller()
        master = defer.Deferred(canceller.cancel)
        timeout = defer.Timeout(0.02, master)
        self.assertFalse(timeout.called)
        yield common.delay(None, 0.01)
        self.assertFalse(timeout.called)
        self.assertFalse(master.called)
        master.errback(SpecialError("result"))
        self.assertFailure(timeout, SpecialError)
        yield timeout
        self.assertFalse(canceller.called)

    @defer.inlineCallbacks
    def testCancelingInTime(self):
        canceller = Canceller()
        master = defer.Deferred(canceller.cancel)
        timeout = defer.Timeout(0.05, master)
        self.assertFalse(timeout.called)
        yield common.delay(None, 0.01)
        self.assertFailure(timeout, defer.CancelledError)
        timeout.cancel()
        yield common.delay(None, 0.01)
        self.assertTrue(canceller.called)
