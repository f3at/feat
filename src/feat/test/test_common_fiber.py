# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import fiber

from . import common


class Dummy(object):

    def spam(self):
        pass

    def bacon(self):
        pass

def beans(self):
    pass

def eggs(self):
    pass


def direct_fun_call(result, arg):
    return "direct_fun_call", result, arg

def alt_fun_call(result, fiber, orig, arg):
    return "alt_fun_call", fiber.fiber_id, orig(result, arg)


class AltTest(object):

    def __init__(self, name):
        self.name = name

    def direct_meth_call(self, result, arg):
        return self.name + ".direct_meth_call", result, arg


@fiber.nested
def test_nesting(result, arg):
    f = fiber.Fiber()
    result.append(("1", arg, f))

    f.addCallback(test_nesting_2a, arg + 2)
    f.addCallback(test_nesting_2b, arg + 3)
    f.succeed(result)
    return f

@fiber.nested
def test_nesting_2a(result, arg):
    f = fiber.Fiber()
    result.append(("2a", arg, f))

    f.addCallback(test_nesting_3, arg + 5)
    f.addCallback(test_nesting_end, arg + 7)
    f.succeed(result)
    return f

@fiber.nested
def test_nesting_2b(result, arg):
    f = fiber.Fiber()
    result.append(("2b", arg, f))

    f.addCallback(test_nesting_end, arg + 11)
    f.succeed(result)
    return f

@fiber.nested
def test_nesting_3(result, arg):
    f = fiber.Fiber()
    result.append(("3", arg, f))

    f.addCallback(test_nesting_end, arg + 13)
    f.succeed(result)
    return f

@fiber.nested
def test_nesting_end(result, arg):
    f = fiber.Fiber()
    result.append(("end", arg, f))
    return f.succeed(result)


class NestTest(object):

    def __init__(self, tag):
        self.tag = tag

    @fiber.nested
    def test_nesting(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "1", arg, f))

        f.addCallback(self.test_nesting_2a, arg + 2)
        f.addCallback(self.test_nesting_2b, arg + 3)
        f.succeed(result)
        return f

    @fiber.nested
    def test_nesting_2a(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "2a", arg, f))

        f.addCallback(self.test_nesting_3, arg + 5)
        f.addCallback(self.test_nesting_end, arg + 7)
        f.succeed(result)
        return f

    @fiber.nested
    def test_nesting_2b(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "2b", arg, f))

        f.addCallback(self.test_nesting_end, arg + 11)
        f.succeed(result)
        return f

    @fiber.nested
    def test_nesting_3(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "3", arg, f))

        f.addCallback(self.test_nesting_end, arg + 13)
        f.succeed(result)
        return f

    @fiber.nested
    def test_nesting_end(self, result, arg):
        f = fiber.Fiber()
        result.append((self.tag, "end", arg, f))
        return f.succeed(result)


class TestFiber(common.TestCase):

    def testSnapshot(self):
        o = Dummy()

        f = fiber.Fiber()
        self.assertEqual((None, None, []), f.snapshot(f))

        f.addCallback(o.spam, 42, parrot="dead")
        self.assertEqual((None, None,
                          [("feat.test.test_common_fiber.Dummy.spam", (42,), {"parrot": "dead"},
                            None, None, None)]),
                         f.snapshot(f))

        f.addErrback(beans, 18, slug="mute")
        self.assertEqual((None, None,
                          [("feat.test.test_common_fiber.Dummy.spam", (42,), {"parrot": "dead"},
                            None, None, None),
                           (None, None, None,
                            "feat.test.test_common_fiber.beans", (18,), {"slug": "mute"})]),
                         f.snapshot(f))

        f.addCallbacks(o.bacon, eggs)
        self.assertEqual((None, None,
                          [("feat.test.test_common_fiber.Dummy.spam", (42,), {"parrot": "dead"},
                            None, None, None),
                           (None, None, None,
                             "feat.test.test_common_fiber.beans", (18,), {"slug": "mute"}),
                           ("feat.test.test_common_fiber.Dummy.bacon", None, None,
                            "feat.test.test_common_fiber.eggs", None, None)]),
                         f.snapshot(f))

    def testFunCallWithoutAlternative(self):
        fiber.remove_alternative(direct_fun_call)

        f = fiber.Fiber()
        f.addCallback(direct_fun_call, 18)
        f.succeed(42)

        self.assertEqual(("direct_fun_call", 42, 18), direct_fun_call(42, 18))
        return self.assertAsyncEqual(("direct_fun_call", 42, 18),
                                     f.start())

    def testMethCallWithoutAlternative(self):
        fiber.remove_alternative(AltTest.direct_meth_call)

        o = AltTest("o")

        f = fiber.Fiber()
        f.addCallback(o.direct_meth_call, 18)
        f.succeed(42)

        self.assertEqual(("o.direct_meth_call", 42, 18),
                         o.direct_meth_call(42, 18))
        return self.assertAsyncEqual(("o.direct_meth_call", 42, 18),
                                     f.start())

    def testFunCallWithAlternative(self):
        fiber.set_alternative(direct_fun_call, alt_fun_call)

        f = fiber.Fiber()
        f.addCallback(direct_fun_call, 18)
        f.succeed(42)

        self.assertEqual(("direct_fun_call", 42, 18), direct_fun_call(42, 18))
        return self.assertAsyncEqual(("alt_fun_call", f.fiber_id,
                                      ("direct_fun_call", 42, 18)), f.start())

    def testMethCallWithAlternative(self):
        fiber.set_alternative(AltTest.direct_meth_call, alt_fun_call)

        o = AltTest("o")

        f = fiber.Fiber()
        f.addCallback(o.direct_meth_call, 18)
        f.succeed(42)

        self.assertEqual(("o.direct_meth_call", 42, 18),
                         o.direct_meth_call(42, 18))
        return self.assertAsyncEqual(("alt_fun_call", f.fiber_id,
                                      ("o.direct_meth_call", 42, 18)),
                                      f.start())

    def testAlternativeLimitations(self):
        try:
            fiber.set_alternative(AltTest.direct_meth_call,
                                  AltTest.direct_meth_call)
            self.fail("Method should not be supported "
                      "as fiber alternative call ? ?")
        except RuntimeError:
            pass

    def testNestingIdentifier(self):
        f1 = fiber.Fiber()
        f2 = fiber.Fiber()
        f2.nest(f1)
        self.assertEqual(f1.fiber_id, f2.fiber_id)

    def testFunctionNesting(self):

        def check(result, fiber):
            result = [(n, a, f.fiber_id, f.fiber_depth) for n, a, f in result]
            fid = fiber.fiber_id

            self.assertEqual([('1', 0, fid, 0),
                               ('2a', 2, fid, 1),
                                ('3', 7, fid, 2),
                                 ('end', 20, fid, 3),
                                ('end', 9, fid, 2),
                               ('2b', 3, fid, 1),
                                ('end', 14, fid, 2),
                              ], result)

        f = test_nesting([], 0)
        d = f.start()
        d.addCallback(check, f)
        return d

    def testMethodNesting(self):

        def check(result, fiber, tag):
            result = [(t, n, a, f.fiber_id, f.fiber_depth)
                      for t, n, a, f in result]
            fid = fiber.fiber_id

            self.assertEqual([(tag, '1', 0, fid, 0),
                               (tag, '2a', 2, fid, 1),
                                (tag, '3', 7, fid, 2),
                                 (tag, 'end', 20, fid, 3),
                                (tag, 'end', 9, fid, 2),
                               (tag, '2b', 3, fid, 1),
                                (tag, 'end', 14, fid, 2),
                              ], result)

        o = NestTest("dummy")
        f = o.test_nesting([], 0)
        d = f.start()
        d.addCallback(check, f, "dummy")
        return d


    ### Private Methods ###

    def assertAsyncEqual(self, expected, d):
        def check(result):
            self.assertEqual(expected, result)
        d.addCallback(check)
        return d
