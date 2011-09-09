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
from time import sleep
import os
import signal as python_signal

from feat.test import common
from feat.common import signal, defer


class Handler(object):

    def __init__(self, signum, signal=signal):
        self.called = 0
        self.signum = signum
        signal.signal(signum, self._handler)

    def _handler(self, signum, frame):
        self.called += 1

    def destroy(self):
        signal.unregister(self.signum, self._handler)


class TestSignal(common.TestCase):

    def setUp(self):
        self.signum = signal.SIGUSR1

    @defer.inlineCallbacks
    def testSimpleHandlers(self):
        handlers = map(lambda _: Handler(self.signum), range(3))
        self.assert_called([0, 0, 0], handlers)
        yield self.kill()
        self.assert_called([1, 1, 1], handlers)
        handlers[0].destroy()
        yield self.kill()
        self.assert_called([1, 2, 2], handlers)
        signal.reset()

    @defer.inlineCallbacks
    def testLegacyHandler(self):
        legacy = Handler(self.signum, signal=python_signal)
        yield self.kill()
        self.assert_called([1], [legacy])
        handler = Handler(self.signum)
        yield self.kill()
        self.assert_called([1, 2], [handler, legacy])
        handler.destroy()
        yield self.kill()
        self.assert_called([1, 3], [handler, legacy])
        handler2 = Handler(self.signum)
        self.assert_called([1, 3, 0], [handler, legacy, handler2])
        yield self.kill()
        self.assert_called([1, 4, 1], [handler, legacy, handler2])
        signal.reset()
        yield self.kill()
        self.assert_called([1, 5, 1], [handler, legacy, handler2])

    def tearDown(self):
        python_signal.signal(self.signum, signal.SIG_DFL)

    def assert_called(self, expected, handlers):
        for handler, called in zip(handlers, expected):
            self.assertEqual(called, handler.called)

    def kill(self):
        ourpid = os.getpid()
        os.kill(ourpid, self.signum)
        return common.delay(None, 0.01)
