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
from feat.models import setter

from feat.test import common


class DummyCall(object):

    def __init__(self, name, source=None):
        self.name = name
        self.source = source
        self.payload = None

    def __getattr__(self, attr):

        def fun(*args, **kwargs):
            self.payload = self.name, attr, args, kwargs

        return fun


class DummyAttr(object):

    def __init__(self, name, source=None):
        self.__dict__["name"] = name
        self.__dict__["source"] = source
        self.__dict__["payload"] = None

    def __setattr__(self, attr, value):
        self.__dict__["payload"] = self.name, attr, value


class TestModelsSetter(common.TestCase):

    @defer.inlineCallbacks
    def check_attr(self, ref, context, setter_factory, exp_name):
        setter = setter_factory("tata")
        yield setter(None, context)
        self.assertEqual(ref.payload, (exp_name, "tata", None))

        setter = setter_factory("toto")
        yield setter("spam", context)
        self.assertEqual(ref.payload, (exp_name, "toto", "spam"))

        setter = setter_factory("tutu")
        yield setter("spam", context, param="foo")
        self.assertEqual(ref.payload, (exp_name, "tutu", "spam"))

    @defer.inlineCallbacks
    def check_set(self, ref, context, setter_factory, exp_key, exp_name):
        setter = setter_factory("titi")
        yield setter(None, context)
        self.assertEqual(ref.payload, (exp_name, "titi",
                                       (exp_key, None), {}))

        setter = setter_factory("titi")
        yield setter("spam", context)
        self.assertEqual(ref.payload, (exp_name, "titi",
                                       (exp_key, "spam"), {}))

        setter = setter_factory("titi")
        yield setter("spam", context, foo="bar")
        self.assertEqual(ref.payload, (exp_name, "titi",
                                       (exp_key, "spam"), {}))

    @defer.inlineCallbacks
    def check_setattr(self, ref, context, setter_factory, exp_key, exp_name):
        setter = setter_factory()
        yield setter(None, context)
        self.assertEqual(ref.payload, (exp_name, exp_key, None))

        setter = setter_factory()
        yield setter("spam", context)
        self.assertEqual(ref.payload, (exp_name, exp_key, "spam"))

        setter = setter_factory()
        yield setter("spam", context, param="foo")
        self.assertEqual(ref.payload, (exp_name, exp_key, "spam"))

    @defer.inlineCallbacks
    def testAttr(self):
        source = DummyAttr("source")
        action = DummyAttr("action")
        model = DummyAttr("model", source)
        view = DummyAttr("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_attr(model, context, setter.model_attr, "model")
        yield self.check_attr(source, context, setter.source_attr, "source")
        yield self.check_attr(action, context, setter.action_attr, "action")
        yield self.check_attr(view, context, setter.view_attr, "view")

    @defer.inlineCallbacks
    def testSetAttr(self):
        source = DummyAttr("source")
        action = DummyAttr("action")
        model = DummyAttr("model", source)
        view = DummyAttr("view")
        context = {"model": model, "view": view,
                   "key": "XXX", "action": action}

        yield self.check_setattr(model, context, setter.model_setattr,
                                 "XXX", "model")
        yield self.check_setattr(source, context, setter.source_setattr,
                                 "XXX", "source")
        yield self.check_setattr(action, context, setter.action_setattr,
                                 "XXX", "action")
        yield self.check_setattr(view, context, setter.view_setattr,
                                 "XXX", "view")

    @defer.inlineCallbacks
    def testSet(self):
        source = DummyCall("source")
        action = DummyCall("action")
        model = DummyCall("model", source)
        view = DummyCall("view")
        ctx = {"model": model, "view": view,
               "action": action, "key": 7}

        yield self.check_set(model, ctx, setter.model_set, 7, "model")
        yield self.check_set(source, ctx, setter.source_set, 7, "source")
        yield self.check_set(action, ctx, setter.action_set, 7, "action")
        yield self.check_set(view, ctx, setter.view_set, 7, "view")
