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
import operator

from feat.test import common
from feat.common import mro, defer, fiber


class MroTestBase(mro.FiberMroMixin):

    def __init__(self):
        self._calls = None
        self.reset()

    def reset(self):
        self._calls = list()

    def _call(self, cls, **kwargs):
        self._calls.append((cls, kwargs))
        return fiber.succeed(None)

    def get_keys(self):
        return map(operator.itemgetter(0), self._calls)

    def get_args(self, cls):
        for _cls, kwargs in self._calls:
            if _cls == cls:
                return kwargs
        raise KeyError('Missing calls for cls %r' % (cls, ))


class A(MroTestBase):

    def spam(self, param_A='default', default_none=None, default_true=True):
        assert default_none is None, default_none
        assert default_true is True, default_true
        return self._call(A, param_A=param_A)


class Blank(object):
    pass


class B(A, Blank):

    def spam(self, param_B):
        return self._call(B, param_B=param_B)


class C(B, A):

    def spam(self, default_sth='sth', param_C=None):
        assert default_sth == 'sth', default_sth
        return self._call(C, param_C=param_C)


class D(C):
    pass


class CallMroTest(common.TestCase):

    def setUp(self):
        self.instance = D()

    @defer.inlineCallbacks
    def testCallMro(self):
        f = self.instance.call_mro('spam', param_B='value')
        self.assertIsInstance(f, fiber.Fiber)
        yield f.start()
        self.assertEqual([A, B, C], self.instance.get_keys())
        self.assertEqual(dict(param_A='default'), self.instance.get_args(A))
        self.assertEqual(dict(param_B='value'), self.instance.get_args(B))
        self.assertEqual(dict(param_C=None), self.instance.get_args(C))

        self.instance.reset()
        f = self.instance.call_mro('spam', param_B='value', param_A='override')
        yield f.start()
        self.assertEqual([A, B, C], self.instance.get_keys())
        self.assertEqual(dict(param_A='override'), self.instance.get_args(A))
        self.assertEqual(dict(param_B='value'), self.instance.get_args(B))
        self.assertEqual(dict(param_C=None), self.instance.get_args(C))

        self.instance.reset()
        self.assertRaises(AttributeError, self.instance.call_mro, 'spam',
                          unknown_param='value')

        self.instance.reset()
        # now test missing param
        self.assertRaises(AttributeError, self.instance.call_mro, 'spam')
