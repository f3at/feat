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

from feat.common import defer
from feat.models import effect, call

from feat.test import common


class Dummy(object):

    def __init__(self, value=None):
        self.value = value

    def perform(self, value):
        self.value = value
        return "done"

    def param_filtering(self, value, toto, tata, titi=None, tutu=None):
        return  value, toto, tata, titi, tutu


class TestModelsCall(common.TestCase):

    @defer.inlineCallbacks
    def testDelayCall(self):
        model = Dummy()
        context = {"model": model}

        eff = effect.delay(call.model_perform("perform"), "nop", 0.1)

        self.assertEqual(model.value, None)
        d = eff("spam", context)
        self.assertEqual(model.value, None)
        res = yield d
        self.assertEqual(res, "nop")
        self.assertEqual(model.value, None)
        yield common.delay(None, 0.1)
        self.assertEqual(model.value, "spam")
