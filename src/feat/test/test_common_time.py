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
