# -*- coding: utf-8 -*-
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

import json
import types

from zope.interface import implements

from feat.common import defer, enum, serialization
from feat.common.serialization import json as feat_json
from feat.models import interface, applicationjson, effect, reference
from feat.models import model, action, value, call, getter, setter, effect
from feat.web import document

from feat.test import common


class DummyEnum(enum.Enum):
    a = enum.value(33, "A")
    b = enum.value(42, "B!")


class DummyContext(object):

    implements(interface.IContext)

    def __init__(self, models=None, names=None):
        self.names = tuple(names) if names is not None else ()
        self.models = tuple(models) if models is not None else ()
        self.remaining = ()

    ### public ###

    def get_action_method(self, action):
        return "DUMMY"

    ### IContext ###

    def make_action_address(self, action):
        action_ident = "_" + action.name
        return self.make_model_address(self.names + (action_ident, ))

    def make_model_address(self, location):
        return "/".join(location)

    def descend(self, model):
        return DummyContext(models=self.models + (model, ),
                            names=self.names + (model.name, ))


class DummyError(object):

    implements(interface.IErrorPayload)

    def __init__(self, code, message, debug, trace):
        self.code = code
        self.message = message
        self.debug = debug
        self.trace = trace


class DummySnapshotable(serialization.Snapshotable):

    def __init__(self):
        self.toto = 3.14
        self.tata = u""
        self.titi = None
        self.tutu = u"áéíóú"


class DummyChild(serialization.Snapshotable):

    def __init__(self, value=None):
        self.value = value


class DummyParent(serialization.Snapshotable):

    def __init__(self):
        self.a = DummyChild(1)
        self.b = DummyChild(2)


@serialization.register
class DummySerializable(serialization.Serializable):

    type_name = "dummy"

    def __init__(self):
        self.toto = 1
        self.tata = u"spam"
        self.titi = True
        self.tutu = u"áéíóú"
        self.tete= u""

    def __eq__(self, other):
        return (isinstance(other, type(self))
                and self.toto == other.toto
                and type(self.toto) is type(other.toto)
                and self.tata == other.tata
                and type(self.tata) is type(other.tata)
                and self.titi == other.titi
                and type(self.titi) is type(other.titi)
                and self.tutu == other.tutu
                and type(self.tutu) is type(other.tutu)
                and self.tete == other.tete
                and type(self.tete) is type(other.tete))

    def __ne__(self, other):
        return not self.__eq__(other)


class ListOfInt(value.Collection):
    value.allows(value.Integer())
    value.min_size(1)
    value.max_size(3)


class RootModel(model.Model):
    model.identity("test.root")
    model.attribute("toto", value.String(),
                    getter=getter.model_getattr(),
                    label="TOTO LABEL", desc="TOTO DESC")
    model.attribute("tata", value.Integer(),
                    setter=setter.model_setattr(),
                    label="TATA LABEL")
    model.attribute("titi", value.Boolean(),
                    getter=getter.model_getattr(),
                    setter=setter.model_setattr(),
                    desc="TITI DESC")
    model.attribute("tutu", value.Enum(DummyEnum),
                    getter=getter.model_getattr())
    model.attribute("tete", value.Reference(),
                    getter=effect.local_ref("test"))

    model.child("structs", model="test.structs")
    model.child("refs", model="test.refs")

    model.delete("del", label="DEL LABEL", desc="DEL DESC")
    model.create("post1", value=value.String("FOO"),
                 label="POST1 LABEL")
    model.create("post2", value=ListOfInt(),
                 params=action.Param("param1", value.Integer()),
                 desc="POST2 DESC")
    model.create("post2",
                 params=[action.Param("param1", value.Integer(),
                                      label="PARAM1 LABEL"),
                         action.Param("param2", value.Integer(),
                                      desc="PARAM2 DESC")])

    def __init__(self, source):
        model.Model.__init__(self, source)
        self.toto = "spam"
        self.tata = 42
        self.titi = True
        self.tutu = DummyEnum.b


class StructModel(model.Model):
    model.identity("test.structs")
    model.attribute("dummy1", value.Struct(),
                    getter=getter.model_getattr())
    model.attribute("dummy2", value.Struct(),
                    getter=getter.model_getattr())
    model.attribute("dummy3", value.Struct(),
                    getter=getter.model_getattr())

    def __init__(self, source):
        model.Model.__init__(self, source)
        self.dummy1 = DummySnapshotable()
        self.dummy2 = DummySerializable()
        self.dummy3 = DummyParent()


class ReferenceModel(model.Model):
    model.identity("test.refs")
    model.reference(call.model_call("_get_ref"))

    def _get_ref(self):
        return reference.Local("some", "place")


class TestApplicationJSON(common.TestCase):

    @defer.inlineCallbacks
    def check(self, obj, expected, exp_type=None, encoding="UTF8"):
        doc = document.WritableDocument("application/json",
                                        encoding=encoding)
        ctx = DummyContext(("ROOT", ), ("root", ))
        yield document.write(doc, obj, context=ctx)
        data = doc.get_data()
        self.assertTrue(isinstance(data, str))
        struct = json.loads(unicode(data)) # for "" to unserialize to u""
        if exp_type is not None:
            self.assertTrue(isinstance(struct, exp_type))
        self.assertEqual(expected, struct)
        defer.returnValue(data)

    @defer.inlineCallbacks
    def testErrorWriter(self):
        yield self.check(DummyError(None, None, None, None), {})
        yield self.check(DummyError(42, None, None, None), {u"code": 42})
        yield self.check(DummyError(None, "spam", None, None),
                         {u"message": u"spam"})
        yield self.check(DummyError(None, None, "bacon", None),
                         {u"debug": u"bacon"})
        yield self.check(DummyError(None, None, None, "sausage"),
                         {u"trace": u"sausage"})
        yield self.check(DummyError(42, "spam", "bacon", "sausage"),
                         {u"code": 42,
                          u"message": u"spam",
                          u"debug": u"bacon",
                          u"trace": u"sausage"})

    @defer.inlineCallbacks
    def testBadData(self):
        doc = document.WritableDocument("application/json",
                                        encoding="UTF8")
        ctx = DummyContext(("ROOT", ), ("root", ))
        yield self.asyncErrback(TypeError, document.write, doc,
                                object(), context=ctx)

    @defer.inlineCallbacks
    def testReferenceWriter(self):
        yield self.check(reference.Local("some", "place"),
                         "root/some/place")

    @defer.inlineCallbacks
    def testCompactModelWriter(self):
        rm = RootModel(object())
        yield self.check(rm, {u"structs": u"root/structs",
                              u"refs": u"root/refs",
                              u"toto": u"spam",
                              u"titi": True,
                              u"tutu": u"B!",
                              u"tete": u"root/test/tete"})
        item = yield rm.fetch_item("toto")
        toto = yield item.fetch()
        yield self.check(toto, u"spam")
        item = yield rm.fetch_item("tata")
        tata = yield item.fetch()
        yield self.check(tata, None)
        item = yield rm.fetch_item("titi")
        titi = yield item.fetch()
        yield self.check(titi, True)
        item = yield rm.fetch_item("tutu")
        tutu = yield item.fetch()
        yield self.check(tutu, u"B!")
        item = yield rm.fetch_item("tete")
        tete = yield item.fetch()
        yield self.check(tete, u"root/test/tete")

        item = yield rm.fetch_item("structs")
        structs = yield item.fetch()
        yield self.check(structs, {u"dummy1": {u"tata": u"",
                                               u"titi": None,
                                               u"toto": 3.14,
                                               u"tutu": u"áéíóú"},
                                   u"dummy2": {u".type": u"dummy",
                                               u"tata": u"spam",
                                               u"tete": u"",
                                               u"titi": True,
                                               u"toto": 1,
                                               u"tutu": u"áéíóú"},
                                   u"dummy3": {u"a": {u"value": 1},
                                               u"b": {u"value": 2}}})

        item = yield structs.fetch_item("dummy1")
        dummy1 = yield item.fetch()
        yield self.check(dummy1, {u"tata": u"",
                                  u"titi": None,
                                  u"toto": 3.14,
                                  u"tutu": u"áéíóú"})
        item = yield structs.fetch_item("dummy2")
        dummy2 = yield item.fetch()
        yield self.check(dummy2, {u".type": u"dummy",
                                  u"tata": u"spam",
                                  u"tete": u"",
                                  u"titi": True,
                                  u"toto": 1,
                                  u"tutu": u"áéíóú"})
        item = yield structs.fetch_item("dummy3")
        dummy3 = yield item.fetch()
        yield self.check(dummy3, {u"a": {u"value": 1},
                                  u"b": {u"value": 2}})

        item = yield rm.fetch_item("refs")
        structs = yield item.fetch()
        yield self.check(structs, {u"href": u"root/some/place"})

    @defer.inlineCallbacks
    def testActionPayloadReader(self):

        @defer.inlineCallbacks
        def check(payload, expected):
            doc = document.ReadableDocument(payload, "application/json",
                                            encoding="UTF8")
            obj = yield document.read(doc, interface.IActionPayload)
            self.assertTrue(interface.IActionPayload.providedBy(obj))
            self.assertEqual(obj, expected)

        yield check('', {})
        yield check('"spam"', {u"value": u"spam"})
        yield check('"\xc3\xa1\xc3\xa9\xc3\xad\xc3\xb3\xc3\xba"',
                    {u"value": u"áéíóú"})
        yield check('42', {u"value": 42})
        yield check('true', {u"value": True})
        yield check('null', {u"value": None})
        yield check('3.14', {u"value": 3.14})
        yield check('[1, 2, 3]', {u"value": [1, 2, 3]})

        yield check('{"spam": true}', {u"spam": True})
        yield check('{"value": 1, "param": null}',
                    {u"value": 1, u"param": None})

    @defer.inlineCallbacks
    def testDefaultWriter(self):
        yield self.check("", u"", unicode)
        yield self.check(u"", u"", unicode)
        yield self.check(u"áéíóú", u"áéíóú", unicode)
        yield self.check("\xc3\xa1\xc3\xa9\xc3\xad\xc3\xb3\xc3\xba",
                         u"áéíóú", unicode)
        yield self.check(42, 42, int)
        yield self.check(-33, -33, int)
        yield self.check(0, 0, int)
        yield self.check(3.14, 3.14, float)
        yield self.check(True, True, bool)
        yield self.check(False, False, bool)
        yield self.check(None, None, types.NoneType)
        yield self.check([], [], list)
        yield self.check({}, {}, dict)
        yield self.check((), [], list)

        yield self.check([1, True, None], [1, True, None])
        yield self.check({"toto": "\xc3\xa1\xc3\xa9\xc3\xad\xc3\xb3\xc3\xba",
                          "tata": u"áéíóú"},
                         {u"toto": u"áéíóú", u"tata": u"áéíóú"})

        yield self.check(DummySnapshotable(),
                         {u"tata": u"",
                          u"titi": None,
                          u"toto": 3.14,
                          u"tutu": u"áéíóú"})

        obj = DummySerializable()
        data = yield self.check(obj,
                                {u'.type': u'dummy',
                                 u"tata": u"spam",
                                 u"titi": True,
                                 u"toto": 1,
                                 u"tutu": u"áéíóú",
                                 u"tete": u""})
        obj2 = feat_json.unserialize(data)
        self.assertTrue(isinstance(obj2, DummySerializable))
        self.assertFalse(obj2 is obj)
        self.assertEqual(obj, obj2)

        yield self.check([1, 2, DummySnapshotable()],
                         [1, 2, {u"tata": u"",
                                 u"titi": None,
                                 u"toto": 3.14,
                                 u"tutu": u"áéíóú"}])

        yield self.check({"toto": DummySerializable()},
                         {u"toto": {u'.type': u'dummy',
                                    u"tata": u"spam",
                                    u"titi": True,
                                    u"toto": 1,
                                    u"tutu": u"áéíóú",
                                    u"tete": u""}})

        yield self.check((1, DummyParent(), 2, DummyParent(), 3),
                         [1, {u"a": {u"value": 1}, u"b": {u"value": 2}},
                          2, {u"a": {u"value": 1}, u"b": {u"value": 2}}, 3])

    @defer.inlineCallbacks
    def testEncodings(self):

        @defer.inlineCallbacks
        def check_write(encoding, obj, expected):
            doc = document.WritableDocument("application/json",
                                            encoding=encoding)
            yield document.write(doc, obj)
            data = doc.get_data()
            self.assertTrue(isinstance(data, str))
            self.assertEqual(expected, data)

        @defer.inlineCallbacks
        def check_read(encoding, data, expected):
            doc = document.ReadableDocument(data, "application/json",
                                            encoding=encoding)
            obj = yield document.read(doc, interface.IActionPayload)
            self.assertTrue(interface.IActionPayload.providedBy(obj))
            self.assertEqual(expected, obj)

        py_uni = u"áéíóú"
        py_utf = "\xc3\xa1\xc3\xa9\xc3\xad\xc3\xb3\xc3\xba"
        py_lat = "\xe1\xe9\xed\xf3\xfa"
        json_uni = '"\\u00e1\\u00e9\\u00ed\\u00f3\\u00fa"'

        yield check_write("utf8", py_uni, json_uni)
        yield check_write("utf8", py_utf, json_uni)
        # module encoding is utf8
        yield check_write("utf8", "áéíóú", json_uni)
        yield check_write("latin1", py_uni, json_uni)
        yield check_write("latin1", py_lat, json_uni)

        # not really useful given json is full unicode, but hey !
        yield check_read("utf8", json_uni, {u"value": py_uni})
        yield check_read("latin1", json_uni, {u"value": py_uni})
