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

import collections

from zope.interface import implements

from feat.common import defer
from feat.models import interface, attribute, value

from feat.test import common


class DummyAspect(object):

    implements(interface.IAspect)

    def __init__(self, name, label=None, desc=None):
        self.name = unicode(name)
        self.label = unicode(label) if label is not None else None
        self.desc= unicode(desc) if desc is not None else None


class DummyPropSource(object):

    def __init__(self):
        self.sync = "foo"
        self.async = 8
        self.readonly = "spam"
        self.writeonly = "toto"

    def get_sync(self):
        return self.sync

    def set_sync(self, value):
        self.sync = value

    def get_async(self):

        def doit(_):
            return self.async

        return common.delay(None, 0.01).addCallback(doit)

    def set_async(self, value):

        def doit(value):
            self.async = value

        return common.delay(value, 0.01).addCallback(doit)

    def get_readonly(self):
        return self.readonly

    def set_writeonly(self, value):
        self.writeonly = value


class TestModelsProperty(common.TestCase):

    def mk_getter(self, method_name, exp_source, exp_name):

        def get(value, context):
            source = context["model"].source
            name = context["key"]
            self.assertEqual(value, None)
            self.assertEqual(source, exp_source)
            self.assertEqual(name, exp_name)
            method = getattr(source, method_name)
            return defer.maybeDeferred(method)

        return get

    def mk_setter(self, method_name, exp_source, exp_name):

        def set(value, context):
            source = context["model"].source
            name = context["key"]
            self.assertEqual(source, exp_source)
            self.assertEqual(name, exp_name)
            method = getattr(source, method_name)
            return defer.maybeDeferred(method, value)

        return set

    @defer.inlineCallbacks
    def testSyncProperty(self):
        info = value.String()
        src = DummyPropSource()
        Attr = attribute.MetaAttribute.new("dummy.sync", info,
                                self.mk_getter("get_sync", src, u"sync"),
                                self.mk_setter("set_sync", src, u"sync"))

        aspect = DummyAspect("sync", desc=u"Synchronous value")
        attr = yield Attr.create(src, aspect)

        self.assertTrue(interface.IModel.providedBy(attr))
        self.assertTrue(interface.IAttribute.providedBy(attr))
        self.assertTrue(interface.IValueInfo.providedBy(attr.value_info))
        self.assertFalse(hasattr(attr, "__dict__"))
        self.assertTrue(attr.is_readable)
        self.assertTrue(attr.is_writable)
        self.assertFalse(attr.is_deletable)
        self.assertTrue(attr.value_info, info)
        self.assertEqual(attr.identity, u"dummy.sync")
        self.assertTrue(isinstance(attr.identity, unicode))
        self.assertEqual(attr.name, u"sync")
        self.assertTrue(isinstance(attr.name, unicode))
        self.assertEqual(attr.label, None)
        self.assertEqual(attr.desc, u"Synchronous value")
        self.assertTrue(isinstance(attr.desc, unicode))
        yield self.asyncEqual(0, attr.count_items())
        yield self.asyncIterEqual([], attr.fetch_items())
        yield self.asyncEqual(None, attr.fetch_item("spam"))
        yield self.asyncEqual(2, attr.count_actions())
        actions = yield attr.fetch_actions()
        self.assertEqual(set([a.name for a in actions]),
                         set([u"set", u"get"]))
        action = yield attr.fetch_action("get")
        action_get = action
        self.assertTrue(interface.IModelAction.providedBy(action))
        self.assertEqual(action.name, u"get")
        self.assertTrue(isinstance(action.name, unicode))
        self.assertEqual(action.category, interface.ActionCategories.retrieve)
        self.assertTrue(action.is_idempotent)
        self.assertEqual(action.result_info, info)
        self.assertEqual(action.parameters, [])
        action = yield attr.fetch_action("set")
        action_set = action
        self.assertTrue(interface.IModelAction.providedBy(action))
        self.assertEqual(action.name, u"set")
        self.assertEqual(action.category, interface.ActionCategories.update)
        self.assertEqual(action.result_info, info)
        action = yield attr.fetch_action("delete")
        self.assertEqual(action, None)
        action = yield attr.fetch_action("spam")
        self.assertEqual(action, None)

        self.assertEqual(src.sync, "foo")
        self.assertFalse(isinstance(src.sync, unicode))
        v = yield attr.fetch_value()
        self.assertEqual(v, u"foo")
        self.assertTrue(isinstance(v, unicode))
        v = yield action_get.perform()
        self.assertEqual(v, u"foo")
        self.assertTrue(isinstance(v, unicode))
        yield self.asyncErrback(interface.UnknownParameters,
                                action_get.perform, "bad")
        yield self.asyncErrback(interface.UnknownParameters,
                                action_get.perform, bad=True)
        yield self.asyncErrback(interface.ParameterError,
                                action_get.perform, "bad", "bad")

        self.assertEqual(src.sync, "foo")
        self.assertFalse(isinstance(src.sync, unicode))
        v = yield attr.update_value("bar")
        self.assertEqual(src.sync, u"bar")
        # changed to unicode when validated
        self.assertTrue(isinstance(src.sync, unicode))
        self.assertEqual(v, u"bar")
        self.assertTrue(isinstance(v, unicode))
        v = yield action_set.perform("biz")
        self.assertEqual(src.sync, u"biz")
        self.assertTrue(isinstance(src.sync, unicode))
        self.assertEqual(v, u"biz")
        self.assertTrue(isinstance(v, unicode))

        yield self.asyncErrback(interface.InvalidParameters,
                                attr.update_value, 45)
        yield self.asyncErrback(interface.InvalidParameters,
                                attr.update_value, None)
        yield self.asyncErrback(interface.InvalidParameters,
                                action_set.perform, 45)
        yield self.asyncErrback(interface.InvalidParameters,
                                action_set.perform, None)
        yield self.asyncErrback(interface.MissingParameters,
                                action_set.perform)
        yield self.asyncErrback(interface.MissingParameters,
                                action_set.perform, bad=True)
        yield self.asyncErrback(interface.UnknownParameters,
                                action_set.perform, 5, bad=True)
        yield self.asyncErrback(interface.ParameterError,
                                action_set.perform, 45, 46)

        v = yield attr.fetch_value()
        self.assertEqual(v, u"biz")
        v = yield action_get.perform()
        self.assertEqual(v, u"biz")

    @defer.inlineCallbacks
    def testAsyncProperty(self):
        info = value.Integer()
        src = DummyPropSource()
        Attr = attribute.MetaAttribute.new("dummy.async", info,
                            self.mk_getter("get_async", src, u"async"),
                            self.mk_setter("set_async", src, u"async"))
        aspect = DummyAspect("async", label="Async", desc="Asynchronous value")
        attr = yield Attr.create(src, aspect)

        self.assertTrue(interface.IModelFactory.providedBy(Attr))
        self.assertTrue(interface.IModel.providedBy(attr))
        self.assertTrue(interface.IAttribute.providedBy(attr))

        self.assertTrue(attr.value_info, info)
        yield self.asyncEqual(2, attr.count_actions())
        action_get = yield attr.fetch_action("get")
        action_set = yield attr.fetch_action("set")

        self.assertEqual(src.async, 8)
        v = yield attr.fetch_value()
        self.assertEqual(v, 8)
        v = yield action_get.perform()
        self.assertEqual(v, 8)
        self.assertEqual(src.async, 8)

        v = yield attr.update_value(33)
        self.assertEqual(src.async, 33)
        self.assertEqual(v, 33)
        v = yield action_set.perform(77)
        self.assertEqual(src.async, 77)
        self.assertEqual(v, 77)

        v = yield attr.update_value("123")
        self.assertEqual(src.async, 123)
        self.assertEqual(v, 123)
        v = yield action_set.perform("789")
        self.assertEqual(src.async, 789)
        self.assertEqual(v, 789)

        v = yield attr.fetch_value()
        self.assertEqual(v, 789)
        v = yield action_get.perform()
        self.assertEqual(v, 789)

        yield self.asyncErrback(interface.InvalidParameters,
                                attr.update_value, None)
        yield self.asyncErrback(interface.InvalidParameters,
                                attr.update_value, "XXX")
        yield self.asyncErrback(interface.InvalidParameters,
                                action_set.perform, None)
        yield self.asyncErrback(interface.InvalidParameters,
                                action_set.perform, "XXX")
        yield self.asyncErrback(interface.MissingParameters,
                                action_set.perform)
        yield self.asyncErrback(interface.MissingParameters,
                                action_set.perform, bad="True")
        yield self.asyncErrback(interface.UnknownParameters,
                                action_set.perform, 5, bad="True")

    @defer.inlineCallbacks
    def testReadOnly(self):
        info = value.String()
        src = DummyPropSource()
        factory = attribute.MetaAttribute.new("dummy.readonly", info,
                    self.mk_getter("get_readonly", src, u"readonly"))
        aspect = DummyAspect("readonly")
        attr = yield factory.create(src, aspect)

        self.assertTrue(interface.IModel.providedBy(attr))
        self.assertTrue(interface.IAttribute.providedBy(attr))
        self.assertTrue(interface.IValueInfo.providedBy(attr.value_info))

        self.assertTrue(attr.is_readable)
        self.assertFalse(attr.is_writable)
        self.assertFalse(attr.is_deletable)
        self.assertTrue(attr.value_info, info)
        self.assertEqual(attr.identity, u"dummy.readonly")
        self.assertEqual(attr.name, u"readonly")
        self.assertEqual(attr.label, None)
        self.assertEqual(attr.desc, None)
        yield self.asyncEqual(0, attr.count_items())
        yield self.asyncIterEqual([], attr.fetch_items())
        yield self.asyncEqual(None, attr.fetch_item("spam"))
        yield self.asyncEqual(1, attr.count_actions())
        actions = yield attr.fetch_actions()
        self.assertEqual(set([a.name for a in actions]), set([u"get"]))
        action_get = yield attr.fetch_action("get")
        action = yield attr.fetch_action("set")
        self.assertEqual(action, None)
        action = yield attr.fetch_action("delete")
        self.assertEqual(action, None)
        action = yield attr.fetch_action("spam")
        self.assertEqual(action, None)

        self.assertEqual(src.readonly, "spam")
        v = yield attr.fetch_value()
        self.assertEqual(v, u"spam")
        v = yield action_get.perform()
        self.assertEqual(v, u"spam")
        self.assertEqual(src.readonly, "spam")

        yield self.asyncErrback(interface.NotSupported,
                                attr.update_value, "bar")

    @defer.inlineCallbacks
    def testWriteOnly(self):
        info = value.String()
        src = DummyPropSource()
        factory = attribute.MetaAttribute.new("dummy.writeonly", info,
                setter=self.mk_setter("set_writeonly", src, u"writeonly"))
        aspect = DummyAspect("writeonly")
        attr = yield factory.create(src, aspect)

        self.assertFalse(attr.is_readable)
        self.assertTrue(attr.is_writable)
        self.assertFalse(attr.is_deletable)
        self.assertTrue(attr.value_info, info)
        yield self.asyncEqual(1, attr.count_actions())
        actions = yield attr.fetch_actions()
        self.assertEqual(set([a.name for a in actions]), set([u"set"]))
        action_set = yield attr.fetch_action("set")
        action = yield attr.fetch_action("get")
        self.assertEqual(action, None)

        self.assertEqual(src.writeonly, "toto")
        yield self.asyncErrback(interface.NotSupported, attr.fetch_value)

        v = yield attr.update_value("titi")
        self.assertEqual(src.writeonly, u"titi")
        self.assertEqual(v, u"titi")
        v = yield action_set.perform("tutu")
        self.assertEqual(src.writeonly, u"tutu")
        self.assertEqual(v, u"tutu")
