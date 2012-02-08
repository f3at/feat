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
from feat.models import call, getter, action, value

from feat.models.interface import *
from feat.models.interface import IAspect, IContextMaker

from feat.test import common


class DummySource(object):
    pass


class DummyAspect(object):

    implements(IAspect)

    def __init__(self, name, label=None, desc=None):
        self.name = name
        self.label = label
        self.desc = desc


class DummyModel(object):

    implements(IModel, IContextMaker)

    def __init__(self, source):
        self.name = None
        self.source = source
        self.view = None
        self.value = None

    ### public ###

    def do_add(self, value, toto):
        return value + toto

    def do_sub(self, value, titi):
        return value - titi

    def do_store(self, value):
        self.value = value
        return value

    def do_format(self, value, tata):
        # Convert to str to check result validation
        return "%d %s" % (value, str(tata))

    def do_split(self, value, delim="#"):
        return value.split(delim)

    def do_select(self, value, key):
        return int(value[key])

    def is_enabled(self, action_name):
        return getattr(self, action_name, False)

    ### IContextMaker ###

    def make_context(self, key=None, view=None, action=None):
        return {"model": self,
               "view": view if view is not None else self.view,
               "key": key or self.name,
               "action": action}


class TestAction(action.Action):
    action.label("Test Action")
    action.desc("Some test action")
    action.value(value.Integer(), label="Value", desc="Value description")
    action.result(value.String())
    action.param("toto", value.Integer(), label="Int", desc="Some integer")
    action.param(u"tata", value.String(default="foo"), False)
    action.param("titi", value.Integer(), is_required=False)
    action.effect(call.model_perform("do_add"))
    action.effect(call.model_perform("do_sub", titi=3))
    action.effect(call.model_perform("do_store"))
    action.effect(call.model_perform("do_format"))


class TestStructure(value.Structure):
    value.field("field1", value.Integer(), is_required=True)
    value.field("string", value.String(), is_required=False)
    value.field("field2", value.Integer(6), is_required=False)


class TestAction2(action.Action):
    action.label("Test Action")
    action.desc("Some test action")
    action.result(value.String())
    action.param("struc", TestStructure())
    action.effect(call.action_perform('result'))

    def result(self, struc):
        return str(struc['field1'])


class TestParamOrder1(action.Action):
    action.param("c", value.Integer())
    action.param("b", value.Integer())


class TestParamOrder2(TestParamOrder1):
    action.param("a", value.Integer())
    action.param("c", value.Integer())


class TestSubAction(TestAction):
    action.label(u"Sub Action")
    action.desc(u"Some sub action")
    action.result(value.Integer())
    action.param("delim", value.String(" "), is_required=False,
                 label=u"Delimiter", desc=u"Delimiter parameter")
    action.effect(call.model_perform("do_store"))
    action.effect(call.model_perform("do_split"))
    action.effect(call.model_perform("do_select", 0))


class EmptyAction(action.Action):
    __slots__ = ()


class NoResultAction(action.Action):
    action.effect(getter.action_attr("value"))

    value = "action result"


class StringResultAction(NoResultAction):
    action.result(value.String())


class StaticEnabledAction(action.Action):
    action.enabled(True)


class StaticDisabledAction(action.Action):
    action.enabled(False)


class DynamicAction(action.Action):
    action.enabled(getter.model_get("is_enabled"))


class TestModelsAction(common.TestCase):

    @defer.inlineCallbacks
    def asyncRaises(self, Error, fun, *args, **kwargs):
        try:
            yield fun(*args, **kwargs)
        except Exception, e:
            if not isinstance(e, Error):
                self.fail("Should have raised %s not %s: %s"
                          % (Error.__name__, type(e).__name__, str(e)))
        else:
            self.fail("Should have raised %s: %s" % (Error.__name__, ))

    @defer.inlineCallbacks
    def asyncParamError(self, Error, params, fun, *args, **kwargs):
        try:
            yield fun(*args, **kwargs)
        except Exception, e:
            if not isinstance(e, Error):
                self.fail("Should have raised %s not %s: %s"
                          % (Error.__name__, type(e).__name__, str(e)))
            self.assertEqual(set(params), set(e.parameters))
        else:
            self.fail("Should have raised %s: %s" % (Error.__name__, ))

    def testParamOrder(self):
        source = DummySource()
        model = DummyModel(source)

        a1 = TestParamOrder1(model)
        a2 = TestParamOrder2(model)

        self.assertEqual([p.name for p in a1.parameters], [u"c", u"b"])
        self.assertEqual([p.name for p in a2.parameters], [u"b", u"a", u"c"])

    @defer.inlineCallbacks
    def testAvailability(self):
        source = DummySource()
        model = DummyModel(source)

        action = yield StaticEnabledAction.create(model)
        is_enabled = yield action.fetch_enabled()
        self.assertTrue(is_enabled)

        action = yield StaticDisabledAction.create(model)
        is_enabled = yield action.fetch_enabled()
        self.assertFalse(is_enabled)

        spam_action_aspect = DummyAspect("spam_action")
        spam_action = yield DynamicAction.create(model, spam_action_aspect)
        bacon_action_aspect = DummyAspect("bacon_action")
        bacon_action = yield DynamicAction.create(model, bacon_action_aspect)

        is_enabled = yield spam_action.fetch_enabled()
        self.assertFalse(is_enabled)
        is_enabled = yield bacon_action.fetch_enabled()
        self.assertFalse(is_enabled)

        model.spam_action = True

        is_enabled = yield spam_action.fetch_enabled()
        self.assertTrue(is_enabled)
        is_enabled = yield bacon_action.fetch_enabled()
        self.assertFalse(is_enabled)

        model.bacon_action = True

        is_enabled = yield spam_action.fetch_enabled()
        self.assertTrue(is_enabled)
        is_enabled = yield bacon_action.fetch_enabled()
        self.assertTrue(is_enabled)

        model.spam_action = False

        is_enabled = yield spam_action.fetch_enabled()
        self.assertFalse(is_enabled)
        is_enabled = yield bacon_action.fetch_enabled()
        self.assertTrue(is_enabled)

    @defer.inlineCallbacks
    def testBasics(self):
        source = DummySource()
        model = DummyModel(source)

        empty = yield EmptyAction.create(model)
        self.assertFalse(hasattr(empty, "__dict__"))
        res = yield empty.perform()
        self.assertEqual(res, None)

        without_result = yield NoResultAction.create(model)
        res = yield without_result.perform()
        self.assertEqual(res, None)

        with_result = yield StringResultAction.create(model)
        res = yield with_result.perform()
        self.assertEqual(res, u"action result")
        self.assertTrue(isinstance(res, unicode))

        with_result.value = "new value"
        res = yield with_result.perform()
        self.assertEqual(res, u"new value")
        self.assertTrue(isinstance(res, unicode))

        with_result.value = 44
        yield self.asyncRaises(ValueError, with_result.perform)

    @defer.inlineCallbacks
    def testBaseAction(self):
        source = DummySource()
        model = DummyModel(source)
        aspect = DummyAspect(u"test", u"label", u"desc")
        action = yield TestAction.create(model, aspect)

        self.assertTrue(IModelAction.providedBy(action))
        self.assertEqual(action.name, u"test")
        self.assertTrue(isinstance(action.name, unicode))
        self.assertEqual(action.label, u"label")
        self.assertTrue(isinstance(action.label, unicode))
        self.assertEqual(action.desc, u"desc")
        self.assertTrue(isinstance(action.desc, unicode))
        self.assertTrue(IValueInfo.providedBy(action.result_info))
        enabled = yield action.fetch_enabled()
        self.assertTrue(enabled)

        self.assertEqual(len(action.parameters), 4)
        params = dict([(p.name, p) for p in action.parameters])

        param = params["value"]
        self.assertTrue(IActionParam.providedBy(param))
        self.assertEqual(param.name, "value")
        self.assertTrue(isinstance(param.name, unicode))
        self.assertTrue(IValueInfo.providedBy(param.value_info))
        self.assertEqual(param.label, u"Value")
        self.assertTrue(isinstance(param.label, unicode))
        self.assertEqual(param.desc, u"Value description")
        self.assertTrue(isinstance(param.desc, unicode))
        self.assertTrue(param.is_required)

        param = params["toto"]
        self.assertTrue(IActionParam.providedBy(param))
        self.assertEqual(param.name, "toto")
        self.assertTrue(isinstance(param.name, unicode))
        self.assertTrue(IValueInfo.providedBy(param.value_info))
        self.assertEqual(param.label, u"Int")
        self.assertTrue(isinstance(param.label, unicode))
        self.assertEqual(param.desc, u"Some integer")
        self.assertTrue(isinstance(param.desc, unicode))
        self.assertTrue(param.is_required)

        param = params["titi"]
        self.assertTrue(IActionParam.providedBy(param))
        self.assertEqual(param.name, "titi")
        self.assertTrue(isinstance(param.name, unicode))
        self.assertTrue(IValueInfo.providedBy(param.value_info))
        self.assertEqual(param.label, None)
        self.assertEqual(param.desc, None)
        self.assertFalse(param.is_required)

        param = params["tata"]
        self.assertTrue(IActionParam.providedBy(param))
        self.assertEqual(param.name, "tata")
        self.assertTrue(isinstance(param.name, unicode))
        self.assertTrue(IValueInfo.providedBy(param.value_info))
        self.assertEqual(param.label, None)
        self.assertEqual(param.desc, None)
        self.assertFalse(param.is_required)

        self.assertEqual(model.value, None)
        res = yield action.perform(33, toto=66) # 33 + 66 - 3
        self.assertEqual(res, u"96 foo")
        self.assertTrue(isinstance(res, unicode))
        self.assertEqual(model.value, 96)

        res = yield action.perform(12, toto=66, titi=45) # 12 + 66 - 45
        self.assertEqual(res, u"33 foo")
        self.assertEqual(model.value, 33)

        res = yield action.perform(77, toto=22, tata="bar") # 77 + 22 - 3
        self.assertEqual(res, u"96 bar")
        self.assertEqual(model.value, 96)

        res = yield action.perform("12", toto="3", titi="5") # 12 + 3 - 5
        self.assertEqual(res, u"10 foo")
        self.assertEqual(model.value, 10)

    @defer.inlineCallbacks
    def testStructureParams(self):
        source = DummySource()
        model = DummyModel(source)
        action = yield TestAction2.create(model)

        res = yield action.perform(struc=dict(field1=444))
        self.assertEqual('444', res)

        # now test errors
        try:
            yield action.perform(
                struc=dict(field1='not integer'))
        except InvalidParameters, e:
            self.assertEqual(('struc.field1', ), e.parameters)
        else:
            self.fail("Didn't raise!")

        try:
            yield action.perform(
                struc=dict(field1=2, unknown='a'))
        except UnknownParameters, e:
            self.assertEqual(('struc.unknown', ), e.parameters)
        else:
            self.fail("Didn't raise!")

        try:
            yield action.perform(
                struc=dict())
        except MissingParameters, e:
            self.assertEqual(('struc.field1', ), e.parameters)
        else:
            self.fail("Didn't raise!")

    @defer.inlineCallbacks
    def testSubAction(self):
        source = DummySource()
        model = DummyModel(source)
        action = yield TestSubAction.create(model)

        self.assertTrue(IModelAction.providedBy(action))
        self.assertEqual(action.name, None)
        self.assertEqual(action.label, u"Sub Action")
        self.assertTrue(isinstance(action.label, unicode))
        self.assertEqual(action.desc, u"Some sub action")
        self.assertTrue(isinstance(action.desc, unicode))
        self.assertTrue(IValueInfo.providedBy(action.result_info))
        enabled = yield action.fetch_enabled()
        self.assertTrue(enabled)

        self.assertEqual(len(action.parameters), 5)
        params = dict([(p.name, p) for p in action.parameters])

        param = params[u"value"]
        self.assertTrue(IActionParam.providedBy(param))

        param = params[u"toto"]
        self.assertTrue(IActionParam.providedBy(param))

        param = params[u"titi"]
        self.assertTrue(IActionParam.providedBy(param))

        param = params[u"tata"]
        self.assertTrue(IActionParam.providedBy(param))

        param = params["delim"]
        self.assertTrue(IActionParam.providedBy(param))
        self.assertEqual(param.name, "delim")
        self.assertTrue(isinstance(param.name, unicode))
        self.assertTrue(IValueInfo.providedBy(param.value_info))
        self.assertEqual(param.label, u"Delimiter")
        self.assertTrue(isinstance(param.label, unicode))
        self.assertEqual(param.desc, u"Delimiter parameter")
        self.assertTrue(isinstance(param.desc, unicode))
        self.assertFalse(param.is_required)

        self.assertEqual(model.value, None)
        res = yield action.perform(33, toto=66) # 33 + 66 - 3
        self.assertEqual(res, 96)
        self.assertTrue(isinstance(res, int))
        self.assertEqual(model.value, "96 foo")
        self.assertTrue(isinstance(model.value, str))

        res = yield action.perform(12, toto=66, titi=45) # 12 + 66 - 45
        self.assertEqual(res, 33)
        self.assertEqual(model.value, u"33 foo")

        res = yield action.perform(77, toto=22, tata="bar") # 77 + 22 - 3
        self.assertEqual(res, 96)
        self.assertEqual(model.value, "96 bar")

        res = yield action.perform("12", toto="3", titi="5") # 12 + 3 - 5
        self.assertEqual(res, 10)
        self.assertEqual(model.value, "10 foo")

        yield self.asyncRaises(ValueError, action.perform,
                               42, toto=12, delim="@")

        res = yield action.perform(42, toto=12, delim="@", tata="@ bar")
        self.assertEqual(res, 51)
        self.assertEqual(model.value, "51 @ bar")

    @defer.inlineCallbacks
    def testPerformError(self):
        source = DummySource()
        model = DummyModel(source)
        action = yield TestAction.create(model)
        empty = yield EmptyAction.create(model)

        # No value specified
        yield self.asyncParamError(MissingParameters, ["value", "toto"],
                                   action.perform)
        # Missing parameter
        yield self.asyncParamError(MissingParameters, ["toto"],
                                   action.perform, 0)
        yield self.asyncParamError(MissingParameters, ["toto"],
                                   action.perform, 0, foo=0)
        # Unknown parameter
        yield self.asyncParamError(UnknownParameters, ["foo"],
                                   action.perform, 0, toto=0, foo=0)
        yield self.asyncParamError(UnknownParameters, ["value"],
                                   empty.perform, 0)
        yield self.asyncParamError(UnknownParameters, ["toto"],
                                   empty.perform, toto=0)
        # Only one value allowed
        yield self.asyncParamError(ParameterError, ["value"],
                                   action.perform, 0, 1, toto=0)
        # Invalid values
        yield self.asyncParamError(InvalidParameters, ["value"],
                                   action.perform, "X", toto=0)
        yield self.asyncParamError(InvalidParameters, ["toto"],
                                   action.perform, 0, toto="X")
        yield self.asyncParamError(InvalidParameters, ["value", "toto"],
                                   action.perform, "X", toto="X")
        yield self.asyncParamError(InvalidParameters,
                                   ["value", "toto", "titi"],
                                   action.perform, "X", toto="X", titi="X")
