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

from zope.interface import implements

from feat.common import defer
from feat.models import utils

from feat.test import common


class TestModelsUtils(common.TestCase):

    def testMkClassName(self):
        mk = utils.mk_class_name
        self.assertEqual(mk(), "")
        self.assertEqual(mk("dummy"), "Dummy")
        self.assertEqual(mk(u"dummy"), "Dummy")
        self.assertEqual(mk("dummy", "name"), "DummyName")
        self.assertEqual(mk("dummy", "", "name"), "DummyName")
        self.assertEqual(mk("dummy", u"name"), "DummyName")
        self.assertEqual(mk("some_name", "with-postfix"),
                         "SomeNameWithPostfix")
        self.assertEqual(mk("aaa", "bbb", "ccc", "ddd"), "AaaBbbCccDdd")
        self.assertEqual(mk("aaa.bbb_ccc ddd-eee", "fff ggg.hhh-iii_jjj"),
                         "AaaBbbCccDddEeeFffGggHhhIiiJjj")
        self.assertEqual(mk("SomeName", "SomeName"), "SomeNameSomeName")
