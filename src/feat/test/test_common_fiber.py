# -*- coding utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import reactor, defer
from twisted.python import failure

from feat.common import fiber

from . import common
from feat.interface.fiber import TriggerType


class Dummy(object):

    def spam(self):
        pass

    def bacon(self):
        pass


def beans(self):
    pass


def eggs(self):
    pass


@fiber.woven
def test_weaving(result, arg):
    f = fiber.Fiber()
    result.append(("1", arg, f))

    f.addCallback(test_weaving_2a, arg + 2)
    f.addCallback(test_weaving_2b, arg + 3)
    f.succeed(result)
    return f


@fiber.woven
def test_weaving_2a(result, arg):
    f = fiber.Fiber()
    result.append(("2a", arg, f))

    f.addCallback(test_weaving_3, arg + 5)
    f.addCallback(test_weaving_end, arg + 7)
    f.succeed(result)
    return f


@fiber.woven
def test_weaving_2b(result, arg):
    f = fiber.Fiber()
    result.append(("2b", arg, f))

    f.addCallback(test_weaving_end, arg + 11)
    f.succeed(result)
    return f


@fiber.woven
def test_weaving_3(result, arg):
    f = fiber.Fiber()
    result.append(("3", arg, f))

    f.addCallback(test_weaving_end, arg + 13)
    f.succeed(result)
    return f


@fiber.woven
def test_weaving_end(result, arg):
    f = fiber.Fiber()
    result.append(("end", arg, f))
    return f.succeed(result)


class WeavingDummy(object):

    def __init__(self, tag):
        self.tag = tag

    @fiber.woven
    def test_weaving(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "1", arg, f))

        f.addCallback(self.test_weaving_2a, arg + 2)
        f.addCallback(self.test_weaving_2b, arg + 3)
        f.succeed(result)
        return f

    @fiber.woven
    def test_weaving_2a(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "2a", arg, f))

        f.addCallback(self.test_weaving_3, arg + 5)
        f.addCallback(self.test_weaving_end, arg + 7)
        f.succeed(result)
        return f

    @fiber.woven
    def test_weaving_2b(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "2b", arg, f))

        f.addCallback(self.test_weaving_end, arg + 11)
        f.succeed(result)
        return f

    @fiber.woven
    def test_weaving_3(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "3", arg, f))

        f.addCallback(self.test_weaving_end, arg + 13)
        f.succeed(result)
        return f

    @fiber.woven
    def test_weaving_end(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "end", arg, f))
        return f.succeed(result)


class TestFiber(common.TestCase):

    def testFiberSnapshot(self):
        o = Dummy()

        f = fiber.Fiber()
        self.assertEqual((None, None, []), f.snapshot())

        f.addCallback(o.spam, 42, parrot="dead")
        self.assertEqual((None, None,
                          [(("feat.test.test_common_fiber.Dummy.spam",
                            (42, ), {"parrot": "dead"}), None)]),
                         f.snapshot())

        f.addErrback(beans, 18, slug="mute")
        self.assertEqual((None, None,
                          [(("feat.test.test_common_fiber.Dummy.spam",
                             (42, ), {"parrot": "dead"}),
                            None),
                           (None,
                            ("feat.test.test_common_fiber.beans",
                             (18, ), {"slug": "mute"}))]),
                         f.snapshot())

        f.addCallbacks(o.bacon, eggs)
        self.assertEqual((None, None,
                          [(("feat.test.test_common_fiber.Dummy.spam",
                             (42, ), {"parrot": "dead"}),
                            None),
                           (None,
                            ("feat.test.test_common_fiber.beans",
                             (18, ), {"slug": "mute"})),
                           (("feat.test.test_common_fiber.Dummy.bacon",
                             None, None),
                            ("feat.test.test_common_fiber.eggs",
                             None, None))]),
                         f.snapshot())

        f.succeed("shop")
        self.assertEqual((TriggerType.succeed, "shop",
                          [(("feat.test.test_common_fiber.Dummy.spam",
                             (42, ), {"parrot": "dead"}),
                            None),
                           (None,
                            ("feat.test.test_common_fiber.beans",
                             (18, ), {"slug": "mute"})),
                           (("feat.test.test_common_fiber.Dummy.bacon",
                             None, None),
                            ("feat.test.test_common_fiber.eggs",
                             None, None))]),
                         f.snapshot())

    def testChainedSnapshot(self):
        o = Dummy()

        spam_id = "feat.test.test_common_fiber.Dummy.spam"
        bacon_id = "feat.test.test_common_fiber.Dummy.bacon"
        eggs_id = "feat.test.test_common_fiber.eggs"
        beans_id = "feat.test.test_common_fiber.beans"

        f1 = fiber.Fiber()
        self.assertEqual((None, None, []), f1.snapshot())
        f1.addCallback(o.spam, 1, 2, 3, accompaniment="beans")
        self.assertEqual((None, None,
                          [((spam_id, (1, 2, 3), {"accompaniment": "beans"}),
                            None)]),
                         f1.snapshot())

        f2 = fiber.Fiber()
        self.assertEqual((None, None, []), f2.snapshot())
        f2.addErrback(o.bacon, accompaniment="eggs", extra="spam")
        self.assertEqual((None, None,
                          [(None,
                            (bacon_id, None,
                             {"accompaniment": "eggs", "extra": "spam"}))]),
                         f2.snapshot())

        f3 = fiber.Fiber()
        self.assertEqual((None, None, []), f3.snapshot())
        f3.addBoth(o.spam)
        self.assertEqual((None, None,
                          [((spam_id, None, None), (spam_id, None, None))]),
                         f3.snapshot())

        f2.chain(f3)
        self.assertEqual((None, None,
                          [(None,
                            (bacon_id, None,
                             {"accompaniment": "eggs", "extra": "spam"})),
                           ((spam_id, None, None), (spam_id, None, None))]),
                         f2.snapshot())

        f2.addCallback(eggs)
        self.assertEqual((None, None,
                          [(None,
                            (bacon_id, None,
                             {"accompaniment": "eggs", "extra": "spam"})),
                           ((spam_id, None, None), (spam_id, None, None)),
                           ((eggs_id, None, None), None)]),
                         f2.snapshot())

        f1.chain(f2)
        self.assertEqual((None, None,
                          [((spam_id, (1, 2, 3), {"accompaniment": "beans"}),
                            None),
                            (None,
                            (bacon_id, None,
                             {"accompaniment": "eggs", "extra": "spam"})),
                           ((spam_id, None, None), (spam_id, None, None)),
                           ((eggs_id, None, None), None)]),
                         f1.snapshot())

        f1.addErrback(beans)
        self.assertEqual((None, None,
                          [((spam_id, (1, 2, 3), {"accompaniment": "beans"}),
                            None),
                            (None,
                            (bacon_id, None,
                             {"accompaniment": "eggs", "extra": "spam"})),
                           ((spam_id, None, None), (spam_id, None, None)),
                           ((eggs_id, None, None), None),
                           (None, (beans_id, None, None))]),
                         f1.snapshot())

    def testFiberState(self):

        def depth1():
            state = fiber.get_state()
            self.assertNotEqual(None, state)
            self.assertTrue("root" in state)

            state.add("depth1 in")

            sub_state = depth2()
            self.assertEqual(state, sub_state)
            self.assertTrue("depth2 in" in state)
            self.assertTrue("depth2 out" in state)
            self.assertTrue("depth3" in state)

            state.add("depth1 out")
            return state

        def depth2():
            state = fiber.get_state()
            self.assertNotEqual(None, state)
            self.assertTrue("root" in state)
            self.assertTrue("depth1 in" in state)

            state.add("depth2 in")

            sub_state = depth3()
            self.assertEqual(state, sub_state)
            self.assertTrue("depth3" in state)

            state.add("depth2 out")
            return state

        def depth3():
            state = fiber.get_state()
            self.assertNotEqual(None, state)
            self.assertTrue("root" in state)
            self.assertTrue("depth1 in" in state)
            self.assertTrue("depth2 in" in state)

            state.add("depth3")
            return state

        self.assertEqual(None, fiber.get_state())
        state = set(["root"])
        fiber.set_state(state)
        self.assertEqual(state, fiber.get_state())
        sub_state = depth1()
        # check that all states are reference to the same instance
        self.assertEqual(state, sub_state)

        self.assertTrue("root" in state)
        self.assertTrue("depth1 in" in state)
        self.assertTrue("depth1 out" in state)
        self.assertTrue("depth2 in" in state)
        self.assertTrue("depth2 out" in state)
        self.assertTrue("depth3" in state)

    def testCustomStateDepth(self):

        def set_tag(tag):
            # Extra depth to account for this function frame
            state = fiber.get_state(depth=1)
            if state is None:
                state = set()
                fiber.set_state(state, depth=1)
            state.add(tag)

        def have_tag(tag):
            # Extra depth to account for this function frame
            state = fiber.get_state(depth=1)
            return state and tag in state

        def sub_function():
            self.assertTrue(have_tag("spam"))

        self.assertFalse(have_tag("spam"))
        set_tag("spam")
        self.assertTrue(have_tag("spam"))
        sub_function()

        self.assertNotEqual(None, fiber.get_state())

        # Check exception for invalid depth
        self.assertRaises(RuntimeError, fiber.get_state, depth=-1)
        self.assertRaises(RuntimeError, fiber.get_state, depth=666)
        self.assertRaises(RuntimeError, fiber.set_state, None, depth=666)

    def mkFiberAttachtest(self, Factory):
        r = fiber.RootFiberDescriptor()
        self.assertEqual(0, r.fiber_depth)
        fid = r.fiber_id

        # Fiber 1 initial values
        f1 = Factory()
        self.assertEqual(None, f1.fiber_id)
        self.assertEqual(None, f1.fiber_depth)

        # Fiber 1 after attached
        r.attach(f1)
        self.assertEqual(fid, f1.fiber_id)
        self.assertEqual(1, f1.fiber_depth)

        # Multiple attach are ignored
        r.attach(f1)
        self.assertEqual(fid, f1.fiber_id)
        self.assertEqual(1, f1.fiber_depth)

        # Fiber 2 initial values
        f2 = Factory()
        self.assertEqual(None, f2.fiber_id)
        self.assertEqual(None, f2.fiber_depth)

        # Fiber 2 after attached
        r.attach(f2)
        self.assertEqual(fid, f2.fiber_id)
        self.assertEqual(1, f2.fiber_depth)

        # Multiple attach are ignored
        r.attach(f2)
        self.assertEqual(fid, f2.fiber_id)
        self.assertEqual(1, f2.fiber_depth)

        # Now sub-fibers

        f21 = Factory()
        f2.attach(f21)
        self.assertEqual(fid, f21.fiber_id)
        self.assertEqual(2, f21.fiber_depth)
        f2.attach(f21)
        self.assertEqual(fid, f21.fiber_id)
        self.assertEqual(2, f21.fiber_depth)

        f211 = Factory()
        f21.attach(f211)
        self.assertEqual(fid, f211.fiber_id)
        self.assertEqual(3, f211.fiber_depth)

        f212 = Factory()
        f21.attach(f212)
        self.assertEqual(fid, f212.fiber_id)
        self.assertEqual(3, f212.fiber_depth)

        # Test errors

        self.assertRaises(fiber.FiberError, r.attach, f212)
        self.assertRaises(fiber.FiberError, f1.attach, f212)

    def testFiberAttach(self):
        return self.mkFiberAttachtest(fiber.Fiber)

    def mkFiberCallTest(self, callback, errback, fail):

        def check_fiber(result, fidref):
            # Using a ugly list to pass a reference to the fid
            fid = fidref and fidref[0] or None
            state = fiber.get_state()
            desc = state["descriptor"]
            if fid:
                self.assertEqual(fid, desc.fiber_id)
            else:
                fidref.append(desc.fiber_id)
            return result

        defs = []

        ### Succeed trigger ###

        f = fiber.Fiber()
        self.assertEqual(None, f.fiber_id)
        self.assertEqual(None, f.fiber_depth)

        e = Exception()
        fidref = []

        # Normal callback path
        f.addCallback(callback, 2, value=3)
        f.addCallback(check_fiber, fidref)
        f.addErrback(fail) # Errback should not be called
        f.addBoth(callback, 3, value=5)
        f.addCallback(check_fiber, fidref)
        f.addCallback(callback, 5, value=7)
        f.addCallback(check_fiber, fidref)
        f.addCallbacks(callback, fail, (7, ), {"value": 11})
        f.addCallback(check_fiber, fidref)

        # Failure path
        f.addCallback(callback, 11, exception=e) # raise the exception
        f.addErrback(check_fiber, fidref)
        f.addCallback(fail) # Callback should not be called
        f.addErrback(errback, e)
        f.addErrback(check_fiber, fidref)
        f.addBoth(errback, e)
        f.addErrback(check_fiber, fidref)
        f.addCallbacks(fail, errback, None, None, (e, ), {"value": 13})
        f.addCallback(check_fiber, fidref)
        f.addCallback(callback, 13, value=17) # Failure resolved
        f.addCallback(check_fiber, fidref)

        f.succeed(2)
        defs.append(f.start())
        self.assertNotEqual(None, f.fiber_id)

        ### With fail trigger ###

        f = fiber.Fiber()
        self.assertEqual(None, f.fiber_id)

        e = Exception()
        fidref = []

        # Failure path
        f.addErrback(check_fiber, fidref)
        f.addCallback(fail) # Callback should not be called
        f.addErrback(errback, e)
        f.addErrback(check_fiber, fidref)
        f.addBoth(errback, e)
        f.addErrback(check_fiber, fidref)
        f.addCallbacks(fail, errback, None, None, (e, ), {"value": 17})

        # Normal callback path
        f.addCallback(check_fiber, fidref)
        f.addCallback(callback, 17, value=19)
        f.addErrback(fail) # Errback should not be called
        f.addCallback(check_fiber, fidref)
        f.addBoth(callback, 19, value=23)
        f.addCallback(check_fiber, fidref)
        f.addCallbacks(callback, fail, (23, ), {"value": 29})
        f.addCallback(check_fiber, fidref)

        f.fail(e)
        defs.append(f.start())
        self.assertNotEqual(None, f.fiber_id)

        return defer.DeferredList(defs, fireOnOneErrback=True)

    def testFiberSyncCalls(self):

        def fail(value):
            self.fail("Unexpected call")

        def callback(result, expected, value=None, exception=None):
            self.assertNotEqual(None, fiber.get_state())
            if expected is not None:
                self.assertEqual(expected, result)
            if exception:
                raise exception
            if value is None:
                return result
            return value

        def errback(failure, expected, value=None):
            self.assertNotEqual(None, fiber.get_state())
            if expected is not None:
                self.assertEqual(expected, failure.value)
            if value is None:
                return failure
            return value

        return self.mkFiberCallTest(callback, errback, fail)

    def testFiberAsyncCallsUsingDeferred(self):

        def fail(value):
            self.fail("Unexpected call")

        def raise_error(error):
            raise error

        def callback(result, expected, value=None, exception=None):
            self.assertNotEqual(None, fiber.get_state())
            if expected is not None:
                self.assertEqual(expected, result)
            if exception:
                d = common.break_chain(exception)
                d.addCallback(raise_error)
                return d
            else:
                if value is None:
                    value = result
                return common.break_chain(value)

        def errback(failure, expected, value=None):
            self.assertNotEqual(None, fiber.get_state())
            if expected is not None:
                self.assertEqual(expected, failure.value)
            return common.break_chain(value or failure)

        return self.mkFiberCallTest(callback, errback, fail)

    def testFiberAsyncCallsUsingFibers(self):

        def raise_error(error):
            raise error

        def fail(value):
            self.fail("Unexpected call")

        def callback(result, expected, value=None, exception=None):
            self.assertNotEqual(None, fiber.get_state())
            if expected is not None:
                self.assertEqual(expected, result)
            if exception:
                f = fiber.Fiber()
                f.addCallback(common.break_chain)
                f.addCallback(raise_error)
                f.succeed(exception)
                return f
            else:
                if value is None:
                    value = result
                f = fiber.Fiber()
                f.addCallback(common.break_chain)
                f.succeed(value)
                return f

        def errback(failure, expected, value=None):
            self.assertNotEqual(None, fiber.get_state())
            if expected is not None:
                self.assertEqual(expected, failure.value)
            f = fiber.Fiber()
            f.addCallback(common.break_chain)
            f.succeed(value or failure)
            return f

        return self.mkFiberCallTest(callback, errback, fail)

    def mkChainedFiberTest(self, push):
        f1 = fiber.Fiber()
        f1.addCallback(push, 1)

        f2 = fiber.Fiber()
        f2.addCallback(push, 2)

        f3 = fiber.Fiber()
        f3.addCallback(push, 3)

        f2.chain(f3)
        f2.addCallback(push, 4)

        f1.chain(f2)
        f1.addCallback(push, 5)

        f1.succeed([])

        return self.assertAsyncEqual(None, range(1, 6), f1.start())

    def testChainedFiberSyncCalls(self):

        def push(list, value):
            list.append(value)
            return list

        return self.mkChainedFiberTest(push)

    def testChainedFiberAsyncCalls(self):

        def push(list, value):
            list.append(value)
            return common.break_chain(list)

        return self.mkChainedFiberTest(push)

    def mkTriggerChainTest(self, callback, errback):

        def unexpected(_):
            self.fail("Unexpected call")

        # TRIGGERED
        f1 = fiber.Fiber()
        f1.succeed(0)
        f1.addErrback(unexpected)
        f1.addCallback(callback, 0, 3)
        f1.addErrback(unexpected)
        f1.addCallback(callback, 3, 2)
        f1.addErrback(unexpected)
        f1.addCallback(callback, 5, 2)
        f1.addErrback(unexpected)

        # NOT TRIGGERED, Should get called with master fiber result
        f2 = fiber.Fiber()
        f2.addErrback(unexpected)
        f2.addCallback(callback, 7, 4)
        f2.addErrback(unexpected)
        f2.addCallback(callback, 11, 2)
        f2.addErrback(unexpected)

        # TRIGGERED, the master fiber result should be overridden
        f3 = fiber.Fiber()
        f3.succeed(59)
        f3.addErrback(unexpected)
        f3.addCallback(callback, 59, 2)
        f3.addErrback(unexpected)
        f3.addCallback(callback, 61, 6)
        f3.addErrback(unexpected)

        # NOT TRIGGERED, started with master fiber's result
        f4 = fiber.Fiber()
        f4.addErrback(unexpected)
        f4.addCallback(callback, 67, 4)
        f4.addErrback(unexpected)
        f4.addCallback(callback, 71, "bad") # Make things fail
        f4.addCallback(unexpected)
        f4.addErrback(errback, exp_class=TypeError)
        f4.addCallback(unexpected)

        # TRIGGERED, the failure from the master fiber got overridden
        f5 = fiber.Fiber()
        e1 = ValueError("f5 e1")
        e2 = TypeError("f5 e2")

        try:
            raise e1
        except:
            # Trigger the fiber in the exception context
            # to be able to create a Failure
            f5.fail()

        f5.addCallback(unexpected)
        f5.addErrback(errback, exp_error=e1, exception=e2)
        f5.addCallback(unexpected)
        f5.addErrback(errback, exp_error=e2, exception=e1)
        f5.addCallback(unexpected)

        # NOT TRIGGERED, errback started with master fiber's last failure
        f6 = fiber.Fiber()
        e2 = ValueError("f6 e2")

        f6.addCallback(unexpected)
        f6.addErrback(errback, exp_error=e1, exception=e2)
        f6.addCallback(unexpected)
        f6.addErrback(errback, exp_error=e2, result="recovered")
        f6.addErrback(unexpected)
        f6.addCallback(callback, "recovered", "")
        f6.addErrback(unexpected)

        f1.chain(f2.chain(f3.chain(f4.chain(f5.chain(f6)))))

        d = f1.start()
        d.addCallback(self.assertEqual, "recovered")

        return d

    def testSyncChainingTrigger(self):

        def callback(param, expected, addvalue):
            self.assertEqual(param, expected)
            return param + addvalue

        def errback(failure, exp_error=None, exp_class=None,
                    result=None, exception=None):
            if exp_class:
                self.assertTrue(failure.check(exp_class) is not None)
            if exp_error:
                self.assertEqual(exp_error, failure.value)

            if exception:
                raise exception

            return result or failure

        return self.mkTriggerChainTest(callback, errback)

    def testAsyncChainingTrigger(self):

        def callback(param, expected, addvalue):

            def async(param):
                self.assertEqual(param, expected)
                return param + addvalue

            d = common.break_chain(param)
            d.addCallback(async)
            return d

        def errback(failure, exp_error=None, exp_class=None,
                    result=None, exception=None):

            def async(failure):
                if exp_class:
                    self.assertTrue(failure.check(exp_class) is not None)
                if exp_error:
                    self.assertEqual(exp_error, failure.value)

                if exception:
                    raise exception

                return result or failure

            d = common.break_errback_chain(failure)
            d.addErrback(async)
            return d

        return self.mkTriggerChainTest(callback, errback)

    def testChainedErrors(self):

        def push(failure, l, v):
            l.append(v)
            return failure

        result = []

        f1 = fiber.Fiber()
        f1.addErrback(push, result, 1)

        f2 = fiber.Fiber()
        f2.addErrback(push, result, 2)

        f1.chain(f2)
        f1.addErrback(push, result, 3)

        f1.addErrback(lambda _: result) # Resolving the error

        try:
            raise Exception()
        except:
            f1.fail()

        return self.assertAsyncEqual(None, range(1, 4), f1.start())

    def testFiberDepth(self):

        def check_depth(depth):
            state = fiber.get_state()
            desc = state["descriptor"]
            if not self._fid:
                self._fid = desc.fiber_id
            else:
                self.assertEqual(self._fid, desc.fiber_id)
            self.assertEqual(depth, desc.fiber_depth)

        @fiber.woven
        def mk_fiber(fun1, fun2, expected):
            check_depth(expected)

            f = fiber.Fiber()
            f.addCallback(expect, expected + 1)
            f.addCallback(expect, expected + 1)
            f.addCallback(fun1)
            f.addCallback(expect, expected + 1)
            f.addCallback(fun2)
            f.addCallback(expect, expected + 1)

            return f.succeed()

        @fiber.woven
        def expect(_, expected):
            check_depth(expected)

        @fiber.woven
        def test():
            return mk_fiber(fun1a, fun1b, 0)

        @fiber.woven
        def fun1a(_):
            return mk_fiber(fun2a, fun2b, 1)

        @fiber.woven
        def fun1b(_):
            return mk_fiber(fun2a, fun2b, 1)

        @fiber.woven
        def fun2a(_):
            return mk_fiber(fun3, fun3, 2)

        @fiber.woven
        def fun2b(_):
            return mk_fiber(fun3, fun3, 2)

        @fiber.woven
        def fun3(_):
            check_depth(3)

        self._fid = None
        return test()

    def testFiberErrors(self):
        # Started without trigger
        f = fiber.Fiber()
        self.assertRaises(fiber.FiberTriggerError, f.start)

        # Cannot trigger more multiple time
        f = fiber.Fiber()
        f.succeed()
        self.assertRaises(fiber.FiberTriggerError, f.fail)

        # Cannot trigger chained fibers
        f1 = fiber.Fiber()
        f2 = fiber.Fiber()
        f1.chain(f2)
        self.assertRaises(fiber.FiberTriggerError, f2.succeed)

        # Cannot start chained fibers
        f1 = fiber.Fiber()
        f2 = fiber.Fiber()
        f1.chain(f2)
        self.assertRaises(fiber.FiberStartupError, f2.start)

        # Cannot chain a start fiber
        f1 = fiber.Fiber()
        f1.succeed()
        f1.start()
        f2 = fiber.Fiber()
        self.assertRaises(fiber.FiberStartupError, f1.chain, f2)

        # Cannot trigger more multiple time
        try:
            raise Exception()
        except:
            # Create an exception context for failures to work
            f = fiber.Fiber()
            f.fail()
            self.assertRaises(fiber.FiberTriggerError, f.succeed)

        # Cannot start fibers multiple times
        f = fiber.Fiber()
        f.addCallback(lambda r: r)
        f.succeed()
        f.start()
        self.assertRaises(fiber.FiberStartupError, f.start)

        # Cannot add callback after a fiber has started
        f = fiber.Fiber()
        f.addCallback(lambda r: r)
        f.succeed()
        f.start()
        self.assertRaises(fiber.FiberStartupError, f.addCallback, lambda r: r)

    def testHandWovenSync(self):

        def invfact(value):
            section = fiber.WovenSection()
            section.enter()
            result = 1
            while True:
                if factorial(result) >= value:
                    break
                result += 1
            return section.exit(result)

        def factorial(value):
            section = fiber.WovenSection()
            section.enter()
            result = 1
            while value > 0:
                result *= value
                value -= 1
            return section.exit(result)

        return self.assertAsyncEqual(None, 5, invfact(120))

    def testHandWovenSyncWithFibers(self):

        def invfact(value):
            section = fiber.WovenSection()
            section.enter()
            f = fiber.Fiber()
            f.addCallback(next, 0, value)
            f.succeed(None)
            return section.exit(f)

        def next(fact, value, max):
            section = fiber.WovenSection()
            section.enter()
            if fact and fact >= max:
                return value
            f = fiber.Fiber()
            f.addCallback(factorial)
            f.addCallback(next, value+1, max)
            f.succeed(value+1)
            return section.exit(f)

        def factorial(value):
            section = fiber.WovenSection()
            section.enter()
            result = 1
            while value > 0:
                result *= value
                value -= 1
            return section.exit(result)

        return self.assertAsyncEqual(None, 5, invfact(120))

    def testHandWovenAsyncWithFibers(self):

        def invfact(value):
            section = fiber.WovenSection()
            section.enter()
            f = fiber.Fiber()
            f.addCallback(common.break_chain)
            f.addCallback(next, 0, value)
            f.addCallback(common.break_chain)
            f.succeed(None)
            return section.exit(f)

        def next(fact, value, max):
            section = fiber.WovenSection()
            section.enter()
            if fact and fact >= max:
                return value
            f = fiber.Fiber()
            f.addCallback(common.break_chain)
            f.addCallback(factorial)
            f.addCallback(common.break_chain)
            f.addCallback(next, value+1, max)
            f.addCallback(common.break_chain)
            f.succeed(value+1)
            return section.exit(f)

        def factorial(value):
            section = fiber.WovenSection()
            section.enter()
            result = 1
            while value > 0:
                result *= value
                value -= 1
            return section.exit(result)

        return self.assertAsyncEqual(None, 5, invfact(120))

    def testWovenDecorator(self):

        @fiber.woven
        def invfact(value):
            f = fiber.Fiber()
            f.addCallback(common.break_chain)
            f.addCallback(next, 0, value)
            f.addCallback(common.break_chain)
            f.succeed(None)
            return f

        @fiber.woven
        def next(fact, value, max):
            if fact and fact >= max:
                return value
            f = fiber.Fiber()
            f.addCallback(common.break_chain)
            f.addCallback(factorial)
            f.addCallback(common.break_chain)
            f.addCallback(next, value+1, max)
            f.addCallback(common.break_chain)
            f.succeed(value+1)
            return f

        @fiber.woven
        def factorial(value):
            result = 1
            while value > 0:
                result *= value
                value -= 1
            return result

        return self.assertAsyncEqual(None, 5, invfact(120))

    def testWovenSectionErrors(self):
        section = fiber.WovenSection()

        # Cannot exit section before entering
        self.assertRaises(fiber.FiberError, section.exit)

        # Cannot abort before entering
        self.assertRaises(fiber.FiberError, section.abort)

        section.enter()

        # Cannot enter multiple times
        self.assertRaises(fiber.FiberError, section.enter)

        section.exit()

    @defer.inlineCallbacks
    def testHandWovenExitValues(self):

        def check(result, expected):
            self.assertEqual(expected, result)

        def test_direct(*args):
            if len(args) < 2:
                value, expected = 2*args #tuple multiplication
            else:
                value, expected = args

            section = fiber.WovenSection()
            section.enter()
            result = section.exit(value)
            self.assertNotEqual(result, defer.Deferred)
            self.assertEqual(expected, result)

        def test_callback(*args):
            if len(args) < 2:
                value, expected = 2*args #tuple multiplication
            else:
                value, expected = args

            section = fiber.WovenSection()
            section.enter()
            d = section.exit(value)
            self.assertTrue(isinstance(d, defer.Deferred))
            d.addErrback(self.fail)
            d.addCallback(check, expected)
            return d

        def test_errback(*args):
            if len(args) < 2:
                value, expected = 2*args #tuple multiplication
            else:
                value, expected = args

            section = fiber.WovenSection()
            section.enter()
            result = section.exit(value)
            self.assertTrue(isinstance(result, defer.Deferred))
            result.addCallback(self.fail)
            result.addErrback(check, expected)
            return result

        yield test_callback(None)
        yield test_callback(123)
        yield test_callback(defer.succeed(None), None)
        yield test_callback(defer.succeed(123), 123)
        yield test_callback(fiber.Fiber().succeed(None), None)
        yield test_callback(fiber.Fiber().succeed(123), 123)

        try:
            raise Exception()
        except:
            f = failure.Failure()
            yield test_errback(f)
            yield test_errback(defer.fail(f), f)
            yield test_errback(fiber.Fiber().fail(f), f)

        section = fiber.WovenSection()
        section.enter()

        test_direct(None)
        test_direct(123)
        test_direct([1, 2, 3])
        test_direct(fiber.Fiber().succeed(None))

        try:
            raise Exception()
        except:
            f = failure.Failure()
            test_direct(f)
            test_direct(fiber.Fiber().fail(f))

        yield section.exit()

    def testWovenSectionAbort(self):
        section1 = fiber.WovenSection()
        section1.enter()

        section2 = fiber.WovenSection()
        section2.enter()

        # In section 2
        f2 = fiber.Fiber()
        f2.addBoth(self.fail)
        f2.succeed("Should never happen if aborted")
        self.assertEqual(None, section2.abort(f2))

        # In section 1
        f1 = fiber.Fiber()
        f1.addBoth(self.fail)
        f1.succeed("Should never happen if aborted")
        self.assertEqual(None, section1.abort(f1))

    def testFiberListAttach(self):
        return self.mkFiberAttachtest(lambda: fiber.FiberList([]))

    def mkFiberListTest(self, add, sub, merge, check):
        # Triggered Fiber
        f1 = fiber.Fiber()
        f1.succeed(12)
        f1.addCallback(check, 12)
        f1.addCallback(add, 4)
        f1.addCallback(check, 12 + 4)
        f1.addCallback(add, 1)
        f1.addCallback(check, 12 + 4 + 1)

        # Not Triggered Fiber
        f2 = fiber.Fiber()
        f2.addCallback(check, 33) # From the FiberList trigger bellow
        f2.addCallback(add, 66)
        f2.addCallback(check, 33 + 66)
        f2.addCallback(sub, 24)
        f2.addCallback(check, 33 + 66 - 24)

        # Triggered Fiber List
        f3 = fiber.FiberList([f1, f2])
        f3.succeed(33)
        f3.addCallback(merge)
        f3.addCallback(check, (12 + 4 + 1) + (33 + 66 - 24))
        f3.addCallback(add, 5)
        f3.addCallback(check, 97)

        # Triggered Fiber
        f4 = fiber.Fiber()
        f4.succeed(78)
        f4.addCallback(check, 78)
        f4.addCallback(sub, 18)
        f4.addCallback(check, 78 - 18)
        f4.addCallback(add, 7)
        f4.addCallback(check, 78 - 18 + 7)

        # Not Triggered Fiber
        f5 = fiber.Fiber()
        f5.addCallback(check, 12) # From the top fiber trigger
        f5.addCallback(sub, 77)
        f5.addCallback(check, 12 - 77)
        f5.addCallback(sub, 2)
        f5.addCallback(check, 12 - 77 - 2)

        # Not Triggered Fiber List
        f6 = fiber.FiberList([f4, f5])
        f6.addCallback(merge)
        f6.addCallback(check, (78 - 18 + 7) + (12 - 77 - 2))
        f6.addCallback(sub, 3)
        f6.addCallback(check, -3)

        # Not Triggered Fiber
        f7 = fiber.Fiber()
        f7.addCallback(check, 12) # From top FiberList
        f7.addCallback(add, 5)
        f7.addCallback(check, 12 + 5)

        # Top triggered Fiber List
        f8 = fiber.FiberList([f3, f6, f7])
        f8.addCallback(merge)
        f8.addCallback(check, 97 - 3 + 12 + 5)
        f8.addCallback(sub, 10)
        f8.addCallback(check, 101)
        f8.succeed(12)

        return f8.start()

    def testSyncFiberList(self):

        def add(r, v):
            return r + v

        def sub(r, v):
            return r - v

        def merge(r):
            t = 0
            for s, v in r:
                self.assertTrue(s)
                t += v
            return t

        def check(r, expected):
            self.assertEqual(r, expected)
            return r

        return  self.mkFiberListTest(add, sub, merge, check)

    def testAsyncFiberList(self):

        def add(r, v):
            return common.break_chain(r + v)

        def sub(r, v):
            return common.break_chain(r - v)

        def merge(r):
            t = 0
            for s, v in r:
                self.assertTrue(s)
                t += v
            return common.break_chain(t)

        def check(r, expected):
            self.assertEqual(r, expected)
            return common.break_chain(r)

        return  self.mkFiberListTest(add, sub, merge, check)

    def testFiberListSnapshot(self):
        o = Dummy()

        f1 = fiber.Fiber()
        self.assertEqual((None, None, []), f1.snapshot())

        f1.addCallback(o.spam, 42, parrot="dead")
        f1.addErrback(beans, 18, slug="mute")
        self.assertEqual((None, None,
                          [(("feat.test.test_common_fiber.Dummy.spam",
                             (42, ), {"parrot": "dead"}),
                            None),
                           (None,
                            ("feat.test.test_common_fiber.beans",
                             (18, ), {"slug": "mute"}))]),
                         f1.snapshot())

        f2 = fiber.Fiber()
        self.assertEqual((None, None, []), f2.snapshot())
        f2.addCallbacks(o.bacon, eggs)
        f2.succeed("shop")
        self.assertEqual((TriggerType.succeed, "shop",
                          [(("feat.test.test_common_fiber.Dummy.bacon",
                             None, None),
                            ("feat.test.test_common_fiber.eggs",
                             None, None))]),
                         f2.snapshot())

        f3 = fiber.FiberList([f1, f2])
        self.assertEqual((None, None,
                          [(None, None,
                            [(("feat.test.test_common_fiber.Dummy.spam",
                               (42, ), {"parrot": "dead"}),
                               None),
                              (None,
                               ("feat.test.test_common_fiber.beans",
                                (18, ), {"slug": "mute"}))]),
                           (TriggerType.succeed, "shop",
                            [(("feat.test.test_common_fiber.Dummy.bacon",
                               None, None),
                              ("feat.test.test_common_fiber.eggs",
                               None, None))])]),
                         f3.snapshot())
        try:
            raise Exception()
        except:
            # Need an exception context to create a Failure
            error = failure.Failure()
            f3.fail(error)

        self.assertEqual((TriggerType.fail, error,
                          [(None, None,
                            [(("feat.test.test_common_fiber.Dummy.spam",
                               (42, ), {"parrot": "dead"}),
                               None),
                              (None,
                               ("feat.test.test_common_fiber.beans",
                                (18, ), {"slug": "mute"}))]),
                           (TriggerType.succeed, "shop",
                            [(("feat.test.test_common_fiber.Dummy.bacon",
                               None, None),
                              ("feat.test.test_common_fiber.eggs",
                               None, None))])]),
                         f3.snapshot())

    def testFiberListResult(self):

        def test(d, v1, e1, v2, e2, expected, **kwargs):
            f1 = fiber.Fiber()
            f1.succeed(v1)
            f1.addCallback(common.delay, 0.03)

            f2 = fiber.Fiber()
            f2.fail(e1)
            f2.addErrback(common.delay_errback, 0.02)

            f3 = fiber.Fiber()
            f3.succeed(v2)
            f3.addCallback(common.delay, 0.01)

            f4 = fiber.Fiber()
            f4.fail(e2)
            f4.addErrback(common.delay_errback, 0.04)

            fl = fiber.FiberList([f1, f2, f3, f4], **kwargs)
            fl.succeed()

            if callable(expected):
                if d is None:
                    d = defer.succeed(None)
                d.addBoth(lambda _: fl.start())
                d.addBoth(expected)
            else:
                d = self.assertAsyncEqual(d, expected, fl.start)

            d.addBoth(common.delay, 0.04) # Ensure all callLater are fired
            return d

        def check_on_one_erback(f, error, index):
            self.assertEqual(f.value.subFailure, error)
            self.assertEqual(f.value.index, index)

        try:
            raise ValueError()
        except:
            e1 = failure.Failure()

        try:
            raise TypeError()
        except:
            e2 = failure.Failure()

        d = None

        d = test(d, 18, e1, 42, e2,
                 [(True, 18), (False, e1), (True, 42), (False, e2)],
                 consumeErrors=True)

        d = test(d, 18, e1, 42, e2, (42, 2),
                 consumeErrors=True, fireOnOneCallback=True)

        d = test(d, 18, e1, 42, e2, lambda r: check_on_one_erback(r, e1, 1),
                 consumeErrors=True, fireOnOneErrback=True)


        return d
