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

