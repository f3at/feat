# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import text_helper

from . import common


class TestTextHelper(common.TestCase):

    def testTextDiff(self):
        self.assertEqual([("aaa", "AAA"), ("bbb", "BBB")],
                         text_helper.extract_diff("XXXaaaYYYbbbZZZ",
                                                  "XXXAAAYYYBBBZZZ"))
        self.assertEqual([("XXX", "xxx"), ("YYY", "yyy"), ("ZZZ", "zzz")],
                         text_helper.extract_diff("XXXaaaYYYbbbZZZ",
                                                  "xxxaaayyybbbzzz"))
