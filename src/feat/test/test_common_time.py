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
import time as python_time

from feat.test import common
from feat.common import time, defer


class TimeScaleTest(common.TestCase):

    def testScaledCalls(self):
        d = defer.Deferred()

        time.scale(0.09)
        call = time.callLater(1, d.callback, None)
        self.assertIsInstance(call, time.ScaledDelayedCall)
        fire_time = call.getTime()
        left = fire_time - time.time()
        self.assertApproximates(1, left, 0.01)
        self.assertTrue(0.9 < left <= 1)
        self.assertTrue(call.active())
        return d

    def testGettingTime(self):
        cur_time = python_time.time()
        our_time = time.time()
        self.assertApproximates(cur_time, our_time, 0.01)

        time.scale(0.1)
        cur_time = python_time.time()
        our_time = time.time()
        self.assertApproximates(cur_time /time._get_scale(), our_time, 0.01)

    def testFutureTime(self):
        cur_time = python_time.time()
        fut_time = time.future(1)
        self.assertApproximates(cur_time + 1, fut_time, 0.01)

        time.scale(0.1)
        cur_time = python_time.time()
        fut_time = time.future(1)
        self.assertApproximates(cur_time / time._get_scale() + 1,
                                fut_time, 0.01)
        time_left = time.left(fut_time)
        self.assertApproximates(1, time_left, 0.01)

    def testRessetingCall(self):
        d = defer.Deferred()

        time.scale(0.09)
        call = time.callLater(10, d.callback, None)
        call.reset(1)

        return d
