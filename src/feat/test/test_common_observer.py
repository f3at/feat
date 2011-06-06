from feat.test import common
from feat.common import fiber, defer, observer


class TestObserver(common.TestCase):

    @defer.inlineCallbacks
    def testObservingFiber(self):
        self.observer = observer.Observer(self._gen_fiber)
        d1 = self.observer.initiate()
        self.assertIsInstance(d1, defer.Deferred)
        self.assertTrue(d1.called)

        self.assertTrue(self.observer.active())
        f = self.observer.notify_finish()
        self.assertIsInstance(f, fiber.Fiber)

        self.finish.callback('result')
        self.assertFalse(self.observer.active())
        self.assertEqual('result', self.observer.get_result())
        res = yield d1
        self.assertEqual('result', res)

    def _gen_fiber(self):
        self.finish = defer.Deferred()
        f = fiber.succeed()
        f.add_callback(lambda _: self.finish)
        return f
