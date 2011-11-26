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
from feat.models import getter

from feat.test import common


class DummyCall(object):

    def __init__(self, name, source=None):
        self.name = name
        self.source = source

    def __getattr__(self, attr):

        def fun(*args, **kwargs):
            return (self.name, attr, args, kwargs)

        return fun


class DummyAttr(object):

    def __init__(self, name, source=None):
        self.name = name
        self.source = source

    def __getattr__(self, attr):
        return self.name, attr


class TestModelsGetter(common.TestCase):

    @defer.inlineCallbacks
    def check_attr(self, context, getter_factory, exp_name):
        getter = getter_factory("tata")
        res = yield getter(None, context)
        self.assertEqual(res, (exp_name, "tata"))

        getter = getter_factory("toto")
        res = yield getter("spam", context)
        self.assertEqual(res, (exp_name, "toto"))

        getter = getter_factory("tutu")
        res = yield getter("spam", context, param="foo")
        self.assertEqual(res, (exp_name, "tutu"))

    @defer.inlineCallbacks
    def check_get(self, context, getter_factory, exp_index, exp_name):
        getter = getter_factory("titi")
        res = yield getter(None, context)
        self.assertEqual(res, (exp_name, "titi", (exp_index, ), {}))

        getter = getter_factory("titi")
        res = yield getter("spam", context)
        self.assertEqual(res, (exp_name, "titi", (exp_index, ), {}))

        getter = getter_factory("titi")
        res = yield getter("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "titi", (exp_index, ), {}))

    @defer.inlineCallbacks
    def check_getattr(self, context, getter_factory, exp_index, exp_name):
        getter = getter_factory()
        res = yield getter(None, context)
        self.assertEqual(res, (exp_name, exp_index))

        getter = getter_factory()
        res = yield getter("spam", context)
        self.assertEqual(res, (exp_name, exp_index))

        getter = getter_factory()
        res = yield getter("spam", context, param="foo")
        self.assertEqual(res, (exp_name, exp_index))

    @defer.inlineCallbacks
    def testAttr(self):
        source = DummyAttr("source")
        action = DummyAttr("action")
        model = DummyAttr("model", source)
        view = DummyAttr("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_attr(context, getter.model_attr, "model")
        yield self.check_attr(context, getter.source_attr, "source")
        yield self.check_attr(context, getter.action_attr, "action")
        yield self.check_attr(context, getter.view_attr, "view")

    @defer.inlineCallbacks
    def testGetAttr(self):
        source = DummyAttr("source")
        action = DummyAttr("action")
        model = DummyAttr("model", source)
        view = DummyAttr("view")
        context = {"model": model, "view": view,
                   "key": "XXX", "action": action}

        yield self.check_getattr(context, getter.model_getattr,
                                 "XXX", "model")
        yield self.check_getattr(context, getter.source_getattr,
                                 "XXX", "source")
        yield self.check_getattr(context, getter.action_getattr,
                                 "XXX", "action")
        yield self.check_getattr(context, getter.view_getattr,
                                 "XXX", "view")

    @defer.inlineCallbacks
    def testGet(self):
        source = DummyCall("source")
        action = DummyCall("action")
        model = DummyCall("model", source)
        view = DummyCall("view")
        context = {"model": model, "view": view,
                   "action": action, "key": 7}

        yield self.check_get(context, getter.model_get, 7, "model")
        yield self.check_get(context, getter.source_get, 7, "source")
        yield self.check_get(context, getter.action_get, 7, "action")
        yield self.check_get(context, getter.view_get, 7, "view")
