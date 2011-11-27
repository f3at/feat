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
from feat.models import call

from feat.test import common


class Dummy(object):

    def __init__(self, value=None):
        self.value = value

    def perform(self, value):
        self.value = value
        return "done"

    def param_filtering(self, value, toto, tata, titi=None, tutu=None):
        return  value, toto, tata, titi, tutu


class DummySync(object):

    def __init__(self, name, source=None):
        self.name = name
        self.source = source

    def __getattr__(self, attr):

        def fun(*args, **kwargs):
            return (self.name, attr, args, kwargs)

        return fun


class DummyAsync(object):

    def __init__(self, name, source=None):
        self.name = name
        self.source = source

    def __getattr__(self, attr):

        def fun(*args, **kwargs):
            return common.delay((self.name, attr, args, kwargs), 0.001)

        return fun


class TestModelsCall(common.TestCase):

    @defer.inlineCallbacks
    def check_call(self, context, call_factory, exp_name):
        call = call_factory("toto")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "toto", (), {}))

        call = call_factory("toto", "egg")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "toto", ("egg", ), {}))

        call = call_factory("toto", bacon="spam")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "toto", (), {"bacon": "spam"}))

        call = call_factory("toto", 1, 2, 3, bacon="spam", egg=2)
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "toto", (1, 2, 3),
                               {"bacon": "spam", "egg": 2}))

        call = call_factory("toto")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "toto", (), {}))

        call = call_factory("toto", "egg")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "toto", ("egg", ), {}))

        call = call_factory("toto", bacon="spam")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "toto", (), {"bacon": "spam"}))

        call = call_factory("toto", 1, 2, 3, bacon="spam", egg=2)
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "toto", (1, 2, 3),
                               {"bacon": "spam", "egg": 2}))

    @defer.inlineCallbacks
    def check_filter(self, context, call_factory, exp_name):
        call = call_factory("titi")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "titi", (None, ), {}))

        call = call_factory("titi", "egg")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "titi", (None, "egg"), {}))

        call = call_factory("titi", bacon="spam")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "titi", (None, ), {"bacon": "spam"}))

        call = call_factory("titi", 1, 2, 3, bacon="spam", egg=2)
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "titi", (None, 1, 2, 3),
                               {"bacon": "spam", "egg": 2}))

        call = call_factory("titi")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "titi", ("spam", ), {}))

        call = call_factory("titi", "egg")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "titi", ("spam", "egg", ), {}))

        call = call_factory("titi", bacon="spam")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "titi", ("spam", ),
                               {"bacon": "spam"}))

        call = call_factory("titi", 1, 2, 3, bacon="spam", egg=2)
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "titi", ("spam", 1, 2, 3),
                               {"bacon": "spam", "egg": 2}))

    @defer.inlineCallbacks
    def check_perform(self, context, call_factory, exp_name):
        call = call_factory("tata")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "tata", (), {"value": None}))

        call = call_factory("tata", "egg")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "tata", ("egg", ), {"value": None}))

        call = call_factory("tata", bacon="spam")
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "tata", (),
                               {"value": None, "bacon": "spam"}))

        call = call_factory("tata", 1, 2, 3, bacon="spam", egg=2)
        res = yield call(None, context)
        self.assertEqual(res, (exp_name, "tata", (1, 2, 3),
                               {"value": None, "bacon": "spam", "egg": 2}))

        call = call_factory("tata")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "tata", (),
                               {"value": "spam", "foo": "bar"}))

        call = call_factory("tata", "egg")
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "tata", ("egg", ),
                               {"value": "spam", "foo": "bar"}))

        call = call_factory("tata", bacon="spam")
        res = yield call("spam", context, foo="bar", bar="foo")
        self.assertEqual(res, (exp_name, "tata", (),
                               {"value": "spam", "bacon": "spam",
                                "foo": "bar", "bar": "foo"}))

        call = call_factory("tata", 1, 2, 3, bacon="spam", egg=2)
        res = yield call("spam", context, foo="bar")
        self.assertEqual(res, (exp_name, "tata", (1, 2, 3),
                               {"value": "spam", "bacon": "spam",
                                "egg": 2, "foo": "bar"}))

        call = call_factory("tata", 1, 2, 3, bacon="spam", egg=2)
        res = yield call("spam", context, foo="bar", egg=42)
        self.assertEqual(res, (exp_name, "tata", (1, 2, 3),
                               {"value": "spam", "bacon": "spam",
                                "egg": 42, "foo": "bar"}))

    @defer.inlineCallbacks
    def testSyncCall(self):
        source = DummySync("source")
        action = DummySync("action")
        model = DummySync("model", source)
        view = DummySync("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_call(context, call.model_call, "model")
        yield self.check_call(context, call.source_call, "source")
        yield self.check_call(context, call.action_call, "action")
        yield self.check_call(context, call.view_call, "view")

    @defer.inlineCallbacks
    def testAsyncCall(self):
        source = DummyAsync("source")
        action = DummyAsync("action")
        model = DummyAsync("model", source)
        view = DummyAsync("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_call(context, call.model_call, "model")
        yield self.check_call(context, call.source_call, "source")
        yield self.check_call(context, call.action_call, "action")
        yield self.check_call(context, call.view_call, "view")

    @defer.inlineCallbacks
    def testSyncFilter(self):
        source = DummySync("source")
        action = DummySync("action")
        model = DummySync("model", source)
        view = DummySync("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_filter(context, call.model_filter, "model")
        yield self.check_filter(context, call.source_filter, "source")
        yield self.check_filter(context, call.action_filter, "action")
        yield self.check_filter(context, call.view_filter, "view")

    @defer.inlineCallbacks
    def testAsyncFilter(self):
        source = DummyAsync("source")
        action = DummyAsync("action")
        model = DummyAsync("model", source)
        view = DummyAsync("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_filter(context, call.model_filter, "model")
        yield self.check_filter(context, call.source_filter, "source")
        yield self.check_filter(context, call.action_filter, "action")
        yield self.check_filter(context, call.view_filter, "view")

    @defer.inlineCallbacks
    def testSyncPerform(self):
        source = DummySync("source")
        action = DummySync("action")
        model = DummySync("model", source)
        view = DummySync("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_perform(context, call.model_perform, "model")
        yield self.check_perform(context, call.source_perform, "source")
        yield self.check_perform(context, call.action_perform, "action")
        yield self.check_perform(context, call.view_perform, "view")

    @defer.inlineCallbacks
    def testAsyncPerform(self):
        source = DummyAsync("source")
        action = DummyAsync("action")
        model = DummyAsync("model", source)
        view = DummyAsync("view")
        context = {"model": model, "view": view, "action": action}

        yield self.check_perform(context, call.model_perform, "model")
        yield self.check_perform(context, call.source_perform, "source")
        yield self.check_perform(context, call.action_perform, "action")
        yield self.check_perform(context, call.view_perform, "view")

    @defer.inlineCallbacks
    def testParameterfiltering(self):
        model = Dummy()
        context = {"model": model}

        eff = call.model_perform("param_filtering", 1)
        res = yield eff(0, context, tata=2)
        self.assertEqual(res, (0, 1, 2, None, None))
        res = yield eff(0, context, tata=2, tutu=3)
        self.assertEqual(res, (0, 1, 2, None, 3))
        res = yield eff(0, context, tata=2, spam=42)
        self.assertEqual(res, (0, 1, 2, None, None))

        eff = call.model_perform("param_filtering", 1, tata=2)
        res = yield eff(0, context)
        self.assertEqual(res, (0, 1, 2, None, None))
        res = yield eff(0, context, foo=33)
        self.assertEqual(res, (0, 1, 2, None, None))
        res = yield eff(0, context, tutu=3)
        self.assertEqual(res, (0, 1, 2, None, 3))
        res = yield eff(0, context, tata=88)
        self.assertEqual(res, (0, 1, 88, None, None))
