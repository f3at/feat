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
        d = self.observer.notify_finish()
        self.assertIsInstance(d, defer.Deferred)

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
