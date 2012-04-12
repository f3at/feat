from zope.interface import implements

from feat.common import defer, activity, log
from feat.test import common

from feat.interface.activity import IActivityManager
from feat.interface.activity import IActivityComponent, AlreadyTerminatedError


class DummyComponent(log.Logger, log.LogProxy):

    implements(IActivityComponent)

    def __init__(self, logger, desc):
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)

        self.activity = activity.ActivityManager(desc)
        self._notifier = defer.Notifier()

    def spawn_child(self, desc=None):
        self.info('Spawning child with description: %r', desc)
        c = DummyComponent(self, desc)
        self.activity.register_child(c)
        return c

    def test_call(self, event_name):
        return self._notifier.wait(event_name)

    def callback(self, event_name):
        self._notifier.callback(event_name, None)

    def errback(self, event_name):
        self._notifier.errback(event_name, RuntimeError('fail'))


class TestActivity(common.TestCase):

    def setUp(self):
        self.component = DummyComponent(self, 'root')

    @defer.inlineCallbacks
    def testSingleComponentDeferreds(self):
        a = self.component.activity
        # initialy we are idle
        self.assertTrue(a.idle)

        # now add a Deferred
        d = defer.Deferred()
        uid = a.track(d)
        ac = a.get(uid)
        self.assertFalse(a.idle)
        self.assertTrue(ac.started)
        self.assertEqual(1, len(list(a.iteractivity())))

        # finish the Deferred
        d.callback(None)
        yield d
        self.assertTrue(a.idle)
        self.assertEqual(0, len(list(a.iteractivity())))

        # same should work with failures
        d = defer.Deferred()
        a.track(d)
        self.assertFalse(a.idle)
        d.errback(RuntimeError('fail'))
        self.assertFailure(d, RuntimeError)
        yield d
        self.assertTrue(a.idle)

        # check canceling
        d = defer.Deferred()
        uid = a.track(d)
        ac = a.get(uid)
        ac.cancel()
        self.assertFailure(d, defer.CancelledError)
        yield d
        self.assertTrue(a.idle)

    @defer.inlineCallbacks
    def testSingleComponentCallLaters(self):
        a = self.component.activity
        self.assertTrue(a.idle)
        c = activity.CallLater(0.05, self.component.test_call,
                               args=("test", ))
        uid = a.track(c)
        # check state just after invoking the call
        self.assertIsInstance(uid, unicode)
        self.assertTrue(c.busy)
        self.assertFalse(c.started)
        self.assertFalse(c.done)
        self.assertFalse(a.idle)

        # wait until it gets called
        yield common.delay(None, 0.1)
        self.assertTrue(c.started)
        self.assertFalse(c.done)
        self.assertFalse(a.idle)

        # let it finish
        self.component.callback('test')
        yield a.wait_for_idle()
        self.assertTrue(c.started)
        self.assertTrue(c.done)
        self.assertTrue(a.idle)

    @defer.inlineCallbacks
    def testFailingCallLater(self):
        a = self.component.activity
        self.assertTrue(a.idle)
        c = activity.CallLater(0.05, self.component.test_call,
                               args=("test", ))
        a.track(c)
        yield common.delay(None, 0.1)

        # let it finish
        self.component.errback('test')
        yield a.wait_for_idle()
        self.assertTrue(c.started)
        self.assertTrue(c.done)
        self.assertTrue(a.idle)

    @defer.inlineCallbacks
    def testCancellingCallLaters(self):
        # first check canceling nonstarted
        a = self.component.activity
        self.assertTrue(a.idle)
        c = activity.CallLater(0.05, self.component.test_call,
                               args=("test", ))
        uid = a.track(c)

        cc = a.get(uid) # check that getter wokrs fine (just in case)
        self.assertIdentical(c, cc)

        cc.cancel()
        self.assertTrue(a.idle)

        # let call later start and than cancel it
        c = activity.CallLater(0.05, self.component.test_call,
                               args=("test", ))
        uid = a.track(c)

        yield common.delay(None, 0.1)
        c.cancel()
        self.assertTrue(a.idle)

    @defer.inlineCallbacks
    def testTerminating(self):
        a = self.component.activity
        d = defer.Deferred()
        c1 = activity.CallLater(0.05, self.component.test_call,
                                args=("test", ))
        c2 = activity.CallLater(0.05, self.component.test_call,
                                args=("test2", ), busy=False)
        ac = a.get(a.track(d))
        a.track(c1)
        a.track(c2)

        self.assertFalse(a.idle)

        term_def = a.terminate()
        self.assertIsInstance(term_def, defer.Deferred)
        self.assertFalse(a.terminated)

        self.assertFalse(ac.done)
        self.assertFalse(c1.done)
        self.assertTrue(c2.done) #nonbusy calls are cancelled right away

        yield common.delay(None, 0.1)
        d.callback(None)
        self.component.callback('test')
        yield term_def
        self.assertTrue(a.terminated)

        self.assertRaises(AlreadyTerminatedError, a.track, activity.Custom())

    @defer.inlineCallbacks
    def testChildrenActivityAndTermination(self):
        a1 = IActivityManager(self.component)
        s = self.component.spawn_child()
        a2 = IActivityManager(s)
        a2_1 = IActivityManager(s.spawn_child())
        a3 = IActivityManager(self.component.spawn_child())

        # check iterchildren result
        self.assertEqual(2, len(list(a1.iterchildren())))
        self.assertEqual(1, len(list(a2.iterchildren())))
        self.assertEqual(0, len(list(a2_1.iterchildren())))
        self.assertEqual(0, len(list(a3.iterchildren())))

        self.assertTrue(a1.idle)
        self.assertTrue(a2.idle)
        self.assertTrue(a2_1.idle)
        self.assertTrue(a3.idle)

        d = defer.Deferred()
        a2.track(d)

        self.assertFalse(a1.idle)
        self.assertFalse(a2.idle)
        self.assertTrue(a2_1.idle)
        self.assertTrue(a3.idle)

        d.callback(None)
        self.assertTrue(a1.idle)
        self.assertTrue(a2.idle)
        self.assertTrue(a2_1.idle)
        self.assertTrue(a3.idle)

        # now setup the first child with busy calls
        busy = list()
        not_busy = list()

        for manager in [a1, a2, a2_1, a3]:
            b = activity.Custom()
            busy.append(b)
            manager.track(b)

            nb = activity.Custom(busy=False, started=False)
            not_busy.append(nb)
            manager.track(nb)

        # first terminate a2 and check that I get right values later
        terminate_def = a2.terminate()
        self.assertEqual([False, True, True, False],
                         [x.done for x in not_busy])
        self.assertEqual([False, False, False, False], [x.done for x in busy])

        busy[1].cancel()
        busy[2].cancel()
        yield terminate_def

        self.assertFalse(a1.terminated)
        self.assertTrue(a2.terminated)
        self.assertTrue(a2_1.terminated)
        self.assertFalse(a3.terminated)

        self.assertEqual(1, len(list(a1.iterchildren())))
        self.assertEqual(0, len(list(a3.iterchildren())))

        # now terminate the root manager

        terminate_def = a1.terminate()
        self.assertEqual([True, True, True, True],
                         [x.done for x in not_busy])
        self.assertEqual([False, True, True, False], [x.done for x in busy])
        busy[0].cancel()
        busy[3].cancel()
        yield terminate_def

        self.assertTrue(a1.terminated)
        self.assertTrue(a3.terminated)
