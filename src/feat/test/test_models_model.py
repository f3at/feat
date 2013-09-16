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

import types

from zope.interface import implements

from feat.common import defer, adapter
from feat.models import interface, model, action, value
from feat.models import call, getter, setter, effect
from feat.web import http

from feat.test import common

from feat.models.interface import IMetadataItem


class DummyView(object):

    def __init__(self, num=None):
        self.num = num


class DummyContext(object):

    implements(interface.IContext)

    def __init__(self, models=[], names=[], remaining=[]):
        self.models = tuple(models)
        self.names = tuple(names)
        self.remaining = tuple(remaining)

    def make_action_address(self, action):
        return self.make_model_address(self.names + (action.name, ))

    def make_model_address(self, location):
        host, port = location[0]
        path = "/" + http.tuple2path(location[1:])
        return http.compose(host=host, port=port, path=path)

    def descend(self, model):
        return DummyContext(self.models + (model, ),
                            self.names + (model.name, ))


class DummySource(object):

    def __init__(self):
        self.attr2 = None
        self.attrs = {u"attr3": None}
        self.child = None
        self.views = {u"view1": DummyView(),
                      u"view2": DummyView()}
        self.items = {}

    def get_attr2(self):
        return self.attr2

    def get_attr(self, name):
        return self.attrs[name]

    def set_attr(self, name, value):
        self.attrs[name] = value

    def get_view(self, name):
        return self.views[name]

    def iter_names(self):
        return self.items.iterkeys()

    def get_value(self, name):

        def retrieve(key):
            return self.items[key]

        d = defer.succeed(name)
        d.addCallback(common.delay, 0.01)
        d.addCallback(retrieve)
        return d


class DummyAspect(object):

    implements(interface.IAspect)

    def __init__(self, name, label=None, desc=None):
        self.name = unicode(name)
        self.label = unicode(label) if label is not None else None
        self.desc = unicode(desc) if desc is not None else None


class DummyAction(action.Action):
    __slots__ = ()
    action.label("Default Label")
    action.desc("Default description")


register = model.get_registry().register


@register
@adapter.register(DummySource, interface.IModel)
class DummyModel1(model.Model):
    model.identity("dummy-model1")


@register
class DummyModel2(model.Model):
    model.identity("dummy-model2")


@register
class DummyModel3(model.Model):
    model.identity("dummy-model3")


@register
class TestModel(model.Model):
    __slots__ = ()
    model.identity("test-model")
    model.action("action1", DummyAction)
    model.action("action2", DummyAction,
                 label="Action2 Label",
                 desc="Action2 description")
    model.attribute("attr1", value.Integer())
    model.attribute("attr2", value.String(),
                    getter=call.source_call("get_attr2"),
                    label="Attribute 2",
                    desc="Some attribute")
    model.attribute("attr3", value.Integer(),
                    getter=getter.source_get("get_attr"),
                    setter=setter.source_set("set_attr"))
    model.child("child1", label="Child 1")
    model.child("child2", getter.source_attr("child"),
                model="dummy-model2", label="Child 2")
    model.child("child3", getter.source_attr("child"),
                model=DummyModel3, desc="Third child")
    model.child("view1", view=getter.source_get("get_view"),
                model="test-view")
    model.child("view2", view=getter.source_get("get_view"),
                model="test-view", label="View 2", desc="Second view")
    model.child("view3", model="test-view")
    model.collection("values",
                     child_names=call.source_call("iter_names"),
                     child_source=getter.source_get("get_value"),
                     child_label="Some Value",
                     child_desc="Some dynamic value",
                     label="Some Values", desc="Some dynamic values")


@register
class TestView(model.Model):
    __slots__ = ()
    model.identity("test-view")
    model.attribute("num", value.Integer(),
                    getter=getter.view_attr("num"),
                    setter=setter.view_attr("num"))


@register
class TestCollection(model.Collection):
    __slots__ = ()
    model.identity("test-collection")
    model.child_label("Some Child")
    model.child_desc("Some dynamic child")
    model.child_model(DummyModel2)
    model.child_names(call.source_call("iter_names"))
    model.child_source(getter.source_get("get_value"))
    model.action("action", DummyAction)


@register
class TestModelMeta(model.Model):
    model.identity("test-model-meta")
    model.meta("foo", "foo1")
    model.meta("foo", "foo2", "FOO")
    model.meta("bar", "bar")

    model.child("child1", meta=("spam", "beans"))
    model.child("child2", meta=[("spam", "egg")])
    model.child("child3", meta=[("spam", "tomatoes", "SPAM"),
                                ("spam", "egg")])

    model.child("view", model="test-model-meta",
                meta=[("spam", "foo1", "FOO")])
    model.attribute("attr", value.String(),
                    meta=[("spam", "foo2", "FOO")])
    model.collection("collection",
                     child_source=getter.model_attr("source"),
                     child_model="test-model-meta",
                     child_meta=[("bacon", "dynitem1"),
                                 ("bacon", "dynitem2", "BAR")],
                     model_meta=("bacon", "model"),
                     meta=("spam", "item", "FOO"))

    model.item_meta("child1", "foo", "foo1")
    model.item_meta("child1", "spam", "foo", "FOO")
    model.item_meta("child2", "foo", "foo1")
    model.item_meta("child2", "spam", "foo", "FOO")
    model.item_meta("child3", "foo", "foo1")
    model.item_meta("child3", "spam", "foo", "FOO")
    model.item_meta("view", "foo", "foo2")
    model.item_meta("attr", "foo", "foo3")
    model.item_meta("collection", "foo", "foo4")


@register
class TestReference(model.Model):
    model.identity("test-reference")
    model.child("child", getter.model_attr("source"), model="test-reference")
    model.action("action", DummyAction)


@register
class TestModelEffects(model.Model):
    model.identity("test-model-calls")
    model.attribute("attr1", value.String(),
                    getter.model_attr("attr1"),
                    setter.model_attr("attr1"))
    model.attribute("attr2", value.String(),
                    getter.model_get("get_attr"),
                    setter.model_set("set_attr"))
    model.attribute("attr3", value.String(),
                    call.model_call("get_attr3"),
                    call.model_filter("set_attr3"))
    model.collection("coll1",
                     child_source=getter.model_get("get_child"),
                     child_names=call.model_call("get_child_names"),
                     child_model="test-model-calls")

    def init(self):
        self.attr1 = "foo"
        self.attr2 = "bar"
        self.attr3 = "buz"
        self.childs = {u"toto": object(),
                       u"tata": object()}

    def get_attr(self, name):
        if name == "attr2":
            return self.attr2
        raise KeyError(name)

    def set_attr(self, name, value):
        if name == "attr2":
            self.attr2 = value
            return
        raise KeyError(name)

    def get_attr3(self):
        return self.attr3

    def set_attr3(self, value):
        self.attr3 = value

    def get_child_names(self):
        return self.childs.keys()

    def get_child(self, name):
        return self.childs[name]


class TestModelsModel(common.TestCase):

    def setUp(self):
        self._factories_snapshot = model.snapshot_factories()
        return common.TestCase.setUp(self)

    def tearDown(self):
        model.restore_factories(self._factories_snapshot)
        return common.TestCase.tearDown(self)

    @defer.inlineCallbacks
    def testModelEffects(self):
        mdl = yield TestModelEffects.create(object())

        self.assertEqual(mdl.attr1, "foo")
        i1 = yield mdl.fetch_item("attr1")
        m1 = yield i1.fetch()
        v1 = yield m1.fetch_value()
        self.assertEqual(v1, "foo")
        r1 = yield m1.update_value("spam")
        self.assertEqual(r1, "spam")
        self.assertEqual(mdl.attr1, "spam")
        v1 = yield m1.fetch_value()
        self.assertEqual(v1, "spam")

        self.assertEqual(mdl.attr2, "bar")
        i2 = yield mdl.fetch_item("attr2")
        m2 = yield i2.fetch()
        v2 = yield m2.fetch_value()
        self.assertEqual(v2, "bar")
        r2 = yield m2.update_value("bacon")
        self.assertEqual(r2, "bacon")
        self.assertEqual(mdl.attr2, "bacon")
        v2 = yield m2.fetch_value()
        self.assertEqual(v2, "bacon")

        self.assertEqual(mdl.attr3, "buz")
        i3 = yield mdl.fetch_item("attr3")
        m3 = yield i3.fetch()
        v3 = yield m3.fetch_value()
        self.assertEqual(v3, "buz")
        r3 = yield m3.update_value("sausage")
        self.assertEqual(r3, "sausage")
        self.assertEqual(mdl.attr3, "sausage")
        v3 = yield m3.fetch_value()
        self.assertEqual(v3, "sausage")

        i4 = yield mdl.fetch_item("coll1")
        m4 = yield i4.fetch()
        childs = yield m4.fetch_items()
        self.assertEqual(set([c.name for c in childs]),
                         set(["toto", "tata"]))
        ci1 = yield m4.fetch_item("toto")
        cm1 = yield ci1.fetch()
        self.assertTrue(cm1.source is mdl.childs[u"toto"])
        ci2 = yield m4.fetch_item("tata")
        cm2 = yield ci2.fetch()
        self.assertTrue(cm2.source is mdl.childs[u"tata"])

    @defer.inlineCallbacks
    def testReferences(self):
        m1 = TestReference(object())
        ctx1 = DummyContext([m1], [("dummy.net", None)])

        i1 = yield m1.fetch_item("child")
        self.assertEqual(i1.reference.resolve(ctx1),
                         "http://dummy.net/child")
        a1 = yield m1.fetch_action("action")
        self.assertEqual(a1.reference.resolve(ctx1),
                         "http://dummy.net/action")
        m2 = yield i1.fetch()
        ctx2 = ctx1.descend(m2)
        i2 = yield m1.fetch_item("child")
        self.assertEqual(i2.reference.resolve(ctx2),
                         "http://dummy.net/child/child")
        a2 = yield m1.fetch_action("action")
        self.assertEqual(a2.reference.resolve(ctx2),
                         "http://dummy.net/child/action")

    @defer.inlineCallbacks
    def testModelMeta(self):

        def check(meta, expected):
            self.assertTrue(all(IMetadataItem.providedBy(i) for i in meta))
            self.assertTrue(all(isinstance(i.name, unicode) for i in meta))
            self.assertTrue(all(isinstance(i.value, unicode) for i in meta))
            self.assertTrue(all(i.scheme is None
                                or isinstance(i.scheme, unicode)
                                for i in meta))
            self.assertEqual(set((i.name, i.value, i.scheme) for i in meta),
                             set(expected))

        m = TestModelMeta(object())
        self.assertEqual(set(m.iter_meta_names()),
                         set([u"bar", u"foo"]))
        self.assertEqual(set(type(n) for n in m.iter_meta_names()),
                         set([unicode]))
        self.assertEqual(len(m.get_meta("foo")), 2)
        self.assertEqual(len(m.get_meta("bar")), 1)
        check(m.get_meta("foo"), [(u'foo', u'foo1', None),
                                  (u'foo', u'foo2', u'FOO')])
        check(m.get_meta("bar"), [(u'bar', u'bar', None)])
        check(m.get_meta("spam"), [])

        i = yield m.fetch_item("child1")
        check(i.get_meta("spam"), [(u'spam', u'beans', None),
                                   (u'spam', u'foo', u'FOO')])
        check(i.get_meta("foo"), [(u'foo', u'foo1', None)])
        check(i.get_meta("bar"), [])

        i = yield m.fetch_item("child2")
        check(i.get_meta("spam"), [(u'spam', u'egg', None),
                                   (u'spam', u'foo', u'FOO')])
        check(i.get_meta("foo"), [(u'foo', u'foo1', None)])
        check(i.get_meta("bar"), [])

        i = yield m.fetch_item("child3")
        check(i.get_meta("spam"), [(u'spam', u'egg', None),
                                   (u'spam', u'foo', u'FOO'),
                                   (u'spam', u'tomatoes', u'SPAM')])
        check(i.get_meta("foo"), [(u'foo', u'foo1', None)])
        check(i.get_meta("bar"), [])

        i = yield m.fetch_item("view")
        check(i.get_meta("spam"), [(u'spam', u'foo1', u'FOO')])
        check(i.get_meta("foo"), [(u'foo', u'foo2', None)])

        i = yield m.fetch_item("attr")
        check(i.get_meta("spam"), [(u'spam', u'foo2', u'FOO')])
        check(i.get_meta("foo"), [(u'foo', u'foo3', None)])

        i = yield m.fetch_item("collection")
        check(i.get_meta("spam"), [(u'spam', u'item', u'FOO')])
        check(i.get_meta("foo"), [(u'foo', u'foo4', None)])

        m = yield i.fetch()
        check(m.get_meta("spam"), [])
        check(m.get_meta("foo"), [])
        check(m.get_meta("bacon"), [(u"bacon", u"model", None)])

        i = yield m.fetch_item("dummy")
        check(i.get_meta("spam"), [])
        check(m.get_meta("foo"), [])
        check(i.get_meta("bacon"), [(u"bacon", u"dynitem1", None),
                                    (u"bacon", u"dynitem2", u"BAR")])

    def testFactoryRegistry(self):
        self.assertTrue(model.get_factory("test-model") is TestModel)
        self.assertTrue(model.get_factory(u"test-model") is TestModel)

    def testBasicFields(self):
        s = DummySource()
        m = TestModel(s)

        self.assertTrue(interface.IModelFactory.providedBy(TestModel))
        self.assertTrue(interface.IModel.providedBy(m))
        self.assertFalse(hasattr(m, "__dict__"))

        self.assertEqual(m.identity, u"test-model")
        self.assertTrue(isinstance(m.identity, unicode))
        self.assertEqual(m.name, None)
        self.assertEqual(m.desc, None)

        a = DummyAspect("name", "label", "desc")
        m = yield TestModel.create(s, a)

        self.assertEqual(m.identity, u"test-model")
        self.assertTrue(isinstance(m.identity, unicode))
        self.assertEqual(m.name, u"name")
        self.assertTrue(isinstance(m.name, unicode))
        self.assertEqual(m.label, u"label")
        self.assertTrue(isinstance(m.label, unicode))
        self.assertEqual(m.desc, u"desc")
        self.assertTrue(isinstance(m.desc, unicode))

    @defer.inlineCallbacks
    def testModelActions(self):
        s = DummySource()
        m = TestModel(s)

        yield self.asyncEqual(2, m.count_actions())

        yield self.asyncEqual(True, m.provides_action("action1"))
        yield self.asyncEqual(True, m.provides_action(u"action1"))
        yield self.asyncEqual(True, m.provides_action("action2"))
        yield self.asyncEqual(True, m.provides_action(u"action2"))
        yield self.asyncEqual(False, m.provides_action("dummy"))
        yield self.asyncEqual(False, m.provides_action(u"dummy"))

        yield self.asyncEqual(None, m.fetch_action("dummy"))
        yield self.asyncEqual(None, m.fetch_action(u"dummy"))

        a = yield m.fetch_action("action1")
        self.assertTrue(interface.IModelAction.providedBy(a))
        self.assertFalse(hasattr(a, "__dict__"))
        self.assertEqual(a.name, u"action1")
        self.assertTrue(isinstance(a.name, unicode))
        self.assertEqual(a.label, u"Default Label")
        self.assertTrue(isinstance(a.label, unicode))
        self.assertEqual(a.desc, u"Default description")
        self.assertTrue(isinstance(a.desc, unicode))

        a = yield m.fetch_action("action2")
        self.assertTrue(interface.IModelAction.providedBy(a))
        self.assertEqual(a.name, u"action2")
        self.assertTrue(isinstance(a.name, unicode))
        self.assertEqual(a.label, u"Action2 Label")
        self.assertTrue(isinstance(a.label, unicode))
        self.assertEqual(a.desc, u"Action2 description")
        self.assertTrue(isinstance(a.desc, unicode))

    @defer.inlineCallbacks
    def testModelItems(self):
        s = DummySource()
        s.child = DummySource()
        m = TestModel(s)

        ITEMS = ("attr1", "attr2", "attr3",
                 "child1", "child2", "child3",
                 "view1", "view2", "view3",
                 "values")

        yield self.asyncEqual(len(ITEMS), m.count_items())

        for name in ITEMS:
            yield self.asyncEqual(True, m.provides_item(name))
            yield self.asyncEqual(True, m.provides_item(unicode(name)))

        yield self.asyncEqual(False, m.provides_item("dummy"))
        yield self.asyncEqual(False, m.provides_item(u"dummy"))
        yield self.asyncEqual(None, m.fetch_item("dummy"))
        yield self.asyncEqual(None, m.fetch_item(u"dummy"))

        items = yield m.fetch_items()
        self.assertTrue(isinstance(items, list))
        self.assertEqual(len(items), len(ITEMS))
        ctx = DummyContext([m], [("dummy.net", None)])
        for item in items:
            self.assertTrue(interface.IModelItem.providedBy(item))
            self.assertFalse(hasattr(item, "__dict__"))
            self.assertTrue(isinstance(item.name, (unicode, types.NoneType)))
            self.assertTrue(isinstance(item.label, (unicode, types.NoneType)))
            self.assertTrue(isinstance(item.desc, (unicode, types.NoneType)))
            self.assertTrue(interface.IReference.providedBy(item.reference))
            self.assertEqual(item.reference.resolve(ctx),
                             str("http://dummy.net/" + item.name))
            model = yield item.fetch()
            self.assertTrue(interface.IModel.providedBy(model))
            model = yield item.browse()
            self.assertTrue(interface.IModel.providedBy(model))

    @defer.inlineCallbacks
    def testModelAttribute(self):
        s = DummySource()
        m = TestModel(s)

        # attr1

        attr1_item = yield m.fetch_item(u"attr1")
        self.assertFalse(hasattr(attr1_item, "__dict__"))
        self.assertEqual(attr1_item.name, u"attr1")
        self.assertEqual(attr1_item.label, None)
        self.assertEqual(attr1_item.desc, None)

        attr1 = yield attr1_item.fetch()
        self.assertFalse(hasattr(attr1, "__dict__"))
        self.assertTrue(interface.IAttribute.providedBy(attr1))
        self.assertFalse(attr1.is_readable)
        self.assertFalse(attr1.is_writable)
        self.assertFalse(attr1.is_deletable)
        self.assertEqual(attr1.value_info, value.Integer())
        yield self.asyncIterEqual([], attr1.fetch_actions())
        yield self.asyncIterEqual([], attr1.fetch_items())

        # attr2

        attr2_item = yield m.fetch_item(u"attr2")
        self.assertEqual(attr2_item.name, u"attr2")
        self.assertEqual(attr2_item.label, u"Attribute 2")
        self.assertEqual(attr2_item.desc, u"Some attribute")

        attr2 = yield attr2_item.browse()
        self.assertTrue(interface.IAttribute.providedBy(attr2))
        self.assertTrue(attr2.is_readable)
        self.assertFalse(attr2.is_writable)
        self.assertFalse(attr2.is_deletable)
        self.assertEqual(attr2.value_info, value.String())
        yield self.asyncIterEqual([], attr1.fetch_items())
        actions = yield attr2.fetch_actions()
        self.assertEqual(set([a.name for a in actions]), set([u"get"]))
        action_get = yield attr2.fetch_action(u"get")

        s.attr2 = "foo"
        val = yield attr2.fetch_value()
        self.assertEqual(val, "foo")
        s.attr2 = "bar"
        val = yield action_get.perform()
        self.assertEqual(val, "bar")

        yield self.asyncErrback(interface.NotSupported,
                                attr2.update_value, "fez")
        yield self.asyncErrback(interface.NotSupported,
                                attr2.delete_value)

        # attr3

        attr3_item = yield m.fetch_item(u"attr3")

        attr3 = yield attr3_item.fetch()
        self.assertTrue(interface.IAttribute.providedBy(attr3))
        self.assertTrue(attr3.is_readable)
        self.assertTrue(attr3.is_writable)
        self.assertFalse(attr3.is_deletable)
        self.assertEqual(attr3.value_info, value.Integer())
        yield self.asyncIterEqual([], attr1.fetch_items())
        actions = yield attr3.fetch_actions()
        self.assertEqual(set([a.name for a in actions]),
                         set([u"get", u"set"]))
        action_get = yield attr3.fetch_action(u"get")
        action_set = yield attr3.fetch_action(u"set")

        s.attrs["attr3"] = 42
        val = yield attr3.fetch_value()
        self.assertEqual(val, 42)
        self.assertEqual(42, s.attrs["attr3"])
        s.attrs["attr3"] = 66
        val = yield action_get.perform()
        self.assertEqual(val, 66)
        self.assertEqual(66, s.attrs["attr3"])

        val = yield attr3.update_value("99")
        self.assertEqual(99, s.attrs["attr3"])
        self.assertEqual(99, val)
        val = yield action_set.perform("44")
        self.assertEqual(44, s.attrs["attr3"])
        self.assertEqual(44, val)

        yield self.asyncErrback(interface.NotSupported, attr3.delete_value)

    @defer.inlineCallbacks
    def testModelChild(self):
        src = DummySource()
        mdl = TestModel(src)

        # child1

        child1_item = yield mdl.fetch_item(u"child1")
        self.assertEqual(child1_item.name, u"child1")
        self.assertEqual(child1_item.label, u"Child 1")
        self.assertEqual(child1_item.desc, None)

        child1 = yield child1_item.fetch()
        yield self.asyncIterEqual([], child1.fetch_actions())
        yield self.asyncIterEqual([], child1.fetch_items())

        self.assertTrue(child1.source is src)
        self.assertTrue(isinstance(child1, DummyModel1))

        self.assertEqual(child1.name, u"child1")
        self.assertTrue(isinstance(child1.name, unicode))
        self.assertEqual(child1.label, u"Child 1")
        self.assertTrue(isinstance(child1.label, unicode))
        self.assertEqual(child1.desc, None)

        # child2

        child2_item = yield mdl.fetch_item(u"child2")
        self.assertEqual(child2_item.name, u"child2")
        self.assertEqual(child2_item.label, u"Child 2")
        self.assertEqual(child2_item.desc, None)

        child2 = yield child2_item.browse()
        self.assertEqual(child2, None)
        child2 = yield child2_item.fetch()
        self.assertEqual(child2, None)

        src.child = object()

        child2 = yield child2_item.browse()
        yield self.asyncIterEqual([], child2.fetch_actions())
        yield self.asyncIterEqual([], child2.fetch_items())

        self.assertEqual(child2.name, u"child2")
        self.assertEqual(child2.label, u"Child 2")
        self.assertEqual(child2.desc, None)

        self.assertTrue(child2.source is src.child)
        self.assertTrue(isinstance(child2, DummyModel2))

        # child3

        child3_item = yield mdl.fetch_item(u"child3")
        self.assertEqual(child3_item.name, u"child3")
        self.assertEqual(child3_item.label, None)
        self.assertEqual(child3_item.desc, u"Third child")

        child3 = yield child3_item.fetch()
        yield self.asyncIterEqual([], child3.fetch_actions())
        yield self.asyncIterEqual([], child3.fetch_items())

        self.assertEqual(child3.name, u"child3")
        self.assertEqual(child3.label, None)
        self.assertEqual(child3.desc, u"Third child")

        self.assertTrue(child3.source is src.child)
        self.assertTrue(isinstance(child3, DummyModel3))

    @defer.inlineCallbacks
    def testModelView(self):
        src = DummySource()
        mdl = TestModel(src)
        src.views[u"view1"] = DummyView()
        src.views[u"view1"].num = 33
        src.views[u"view2"] = DummyView()
        src.views[u"view2"].num = 44

        # view1

        view1_item = yield mdl.fetch_item(u"view1")
        self.assertFalse(hasattr(view1_item, "__dict__"))
        self.assertEqual(view1_item.name, u"view1")
        self.assertEqual(view1_item.label, None)
        self.assertEqual(view1_item.desc, None)

        view1 = yield view1_item.fetch()
        self.assertFalse(hasattr(view1, "__dict__"))
        self.assertTrue(isinstance(view1, TestView))
        self.assertTrue(view1.source is src)
        self.assertTrue(view1.aspect is not None)
        self.assertTrue(view1.view is src.views[u"view1"])
        view1_num_item = yield view1.fetch_item("num")
        view1_num = yield view1_num_item.fetch()
        self.assertTrue(view1_num.source is src)
        self.assertTrue(view1_num.view is src.views[u"view1"])
        num = yield view1_num.fetch_value()
        self.assertEqual(num, 33)
        ret = yield view1_num.update_value("55")
        self.assertEqual(ret, 55)
        self.assertEqual(src.views[u"view1"].num, 55)

        # view2

        view2_item = yield mdl.fetch_item(u"view2")
        self.assertEqual(view2_item.name, u"view2")
        self.assertEqual(view2_item.label, u"View 2")
        self.assertEqual(view2_item.desc, u"Second view")

        view2 = yield view2_item.fetch()
        self.assertTrue(isinstance(view2, TestView))
        self.assertTrue(view2.source is src)
        self.assertTrue(view2.aspect is not None)
        self.assertTrue(view2.view is src.views[u"view2"])
        view2_num_item = yield view2.fetch_item("num")
        view2_num = yield view2_num_item.fetch()
        self.assertTrue(view2_num.source is src)
        self.assertTrue(view2_num.view is src.views[u"view2"])
        num = yield view2_num.fetch_value()
        self.assertEqual(num, 44)
        ret = yield view2_num.update_value("66")
        self.assertEqual(ret, 66)
        self.assertEqual(src.views[u"view2"].num, 66)

        # view3

        view3_item = yield mdl.fetch_item(u"view3")
        self.assertEqual(view3_item.name, u"view3")
        self.assertEqual(view3_item.label, None)
        self.assertEqual(view3_item.desc, None)

        view3 = yield view3_item.fetch()
        self.assertTrue(isinstance(view3, TestView))
        self.assertTrue(view3.source is src)
        self.assertTrue(view3.aspect is not None)
        self.assertTrue(view3.view is None)

    @defer.inlineCallbacks
    def testDeclaredCollection(self):
        asp = DummyAspect("collec")
        src = DummySource()
        mdl = yield TestCollection.create(src, asp)

        self.assertTrue(interface.IModel.providedBy(mdl))
        self.assertFalse(hasattr(mdl, "__dict__"))

        yield self.asyncEqual(1, mdl.count_actions())
        action = yield mdl.fetch_action("action")
        self.assertTrue(isinstance(action, DummyAction))
        actions = yield mdl.fetch_actions()
        self.assertEqual(set([u"action"]),
                         set([a.name for a in actions]))
        yield self.asyncEqual(None, mdl.fetch_action("spam"))


        yield self.asyncEqual(0, mdl.count_items())
        yield self.asyncEqual(False, mdl.provides_item("spam"))

        src.items[u"source1"] = object()
        src.items[u"source2"] = object()
        src.items[u"source3"] = object()

        yield self.asyncEqual(3, mdl.count_items())
        yield self.asyncEqual(True, mdl.provides_item("source1"))
        yield self.asyncEqual(True, mdl.provides_item(u"source1"))
        yield self.asyncEqual(False, mdl.provides_item(u"spam"))

        items = yield mdl.fetch_items()
        self.assertTrue(isinstance(items, list))
        self.assertEqual(len(items), len(src.items))
        for (k, o), item in zip(src.items.items(), items):
            self.assertFalse(hasattr(item, "__dict__"))
            self.assertEqual(item.name, k)
            self.assertTrue(isinstance(item.name, unicode))
            self.assertEqual(item.label, u"Some Child")
            self.assertTrue(isinstance(item.label, unicode))
            self.assertEqual(item.desc, u"Some dynamic child")
            self.assertTrue(isinstance(item.desc, unicode))

            def check_model(m):
                self.assertTrue(isinstance(m, DummyModel2))
                self.assertTrue(m.source is o)
                self.assertEqual(m.name, k)
                self.assertTrue(isinstance(m.name, unicode))
                self.assertEqual(m.label, u"Some Child")
                self.assertTrue(isinstance(m.label, unicode))
                self.assertEqual(m.desc, u"Some dynamic child")
                self.assertTrue(isinstance(m.desc, unicode))

            fm = yield item.fetch()
            check_model(fm)

            bm = yield item.browse()
            check_model(bm)

        source1_item = yield mdl.fetch_item("source1")
        self.assertTrue(interface.IModelItem.providedBy(source1_item))
        self.assertFalse(hasattr(source1_item, "__dict__"))
        self.assertEqual(item.name, u"source1")

        source1 = yield source1_item.fetch()
        self.assertTrue(isinstance(source1, DummyModel2))
        self.assertTrue(source1.source is src.items[u"source1"])

        yield self.asyncEqual(None, mdl.fetch_item("spam"))

    @defer.inlineCallbacks
    def testAnnotatedCollection(self):
        src = DummySource()
        mdl = TestModel(src)

        yield self.asyncEqual(True, mdl.provides_item("values"))
        mdl_item = yield mdl.fetch_item("values")
        self.assertFalse(hasattr(mdl_item, "__dict__"))
        self.assertEqual(mdl_item.name, u"values")
        self.assertTrue(isinstance(mdl_item.name, unicode))
        self.assertEqual(mdl_item.label, u"Some Values")
        self.assertTrue(isinstance(mdl_item.label, unicode))
        self.assertEqual(mdl_item.desc, u"Some dynamic values")
        self.assertTrue(isinstance(mdl_item.desc, unicode))

        src.items[u"value1"] = DummySource()
        src.items[u"value2"] = DummySource()

        mdl = yield mdl_item.fetch()
        self.assertTrue(interface.IModel.providedBy(mdl))
        self.assertFalse(hasattr(mdl, "__dict__"))
        yield self.asyncEqual(2, mdl.count_items())
        yield self.asyncEqual(True, mdl.provides_item("value1"))
        yield self.asyncEqual(True, mdl.provides_item(u"value2"))
        yield self.asyncEqual(False, mdl.provides_item(u"spam"))
        items = yield mdl.fetch_items()
        self.assertEqual(2, len(items))
        self.assertEqual(set([u"value1", u"value2"]),
                         set([i.name for i in items]))
        for i in items:
            self.assertTrue(interface.IModelItem.providedBy(i))
            self.assertFalse(hasattr(i, "__dict__"))
            self.assertTrue(isinstance(i.name, unicode))
            self.assertEqual(i.label, u"Some Value")
            self.assertTrue(isinstance(i.label, unicode))
            self.assertEqual(i.desc, u"Some dynamic value")
            self.assertTrue(isinstance(i.desc, unicode))
            fm = yield i.fetch()
            self.assertTrue(interface.IModel.providedBy(fm))
            self.assertTrue(isinstance(fm, DummyModel1))
            bm = yield i.fetch()
            self.assertTrue(interface.IModel.providedBy(bm))
            self.assertTrue(isinstance(bm, DummyModel1))

        value1_item = yield mdl.fetch_item("value1")
        value1 = yield value1_item.fetch()
        self.assertTrue(value1.source is src.items[u"value1"])

        value2_item = yield mdl.fetch_item(u"value2")
        value2 = yield value2_item.fetch()
        self.assertTrue(value2.source is src.items[u"value2"])

        yield self.asyncEqual(None, mdl.fetch_item("spam"))
