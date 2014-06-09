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
import pprint
import types
import StringIO

from zope.interface import implements

from feat.common import defer, enum, serialization, deep_compare
from feat.common.serialization import json as feat_json
from feat.models import interface, applicationjson, effect, reference
from feat.models import model, action, value, call, getter, setter
from feat.web import document, http

from feat.test import common
from feat.models.interface import ErrorTypes


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
        return http.Methods.POST

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

    def __init__(self, type, code, message, subjects, reasons, debug):
        self.error_type = type
        self.error_code = code
        self.message = message
        self.subjects = subjects
        self.reasons = reasons
        self.debug = debug
        self.stamp = None


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

    type_name = "json-dummy"

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
    value.label("List Of Int")
    value.desc("List of integers")
    value.allows(value.Integer())
    value.min_size(1)
    value.max_size(3)
    value.meta("type-meta", "METAVALUE")


class ActionTest(action.Action):
    action.label("Test Action")
    action.desc("Test action description")
    action.param("param1", value.Integer(), label="PARAM1 LABEL")
    action.param("param2", value.Integer(), desc="PARAM2 DESC")
    action.meta("action-meta", "METAVALUE")


register = model.get_registry().register


@register
class RootModelTest(model.Model):
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
    model.child("inline", model="test.inline")
    model.item_meta('inline', 'json', 'render-inline')
    model.child("refs", model="test.refs")

    model.delete("del", label="DEL LABEL", desc="DEL DESC")
    model.create("post1", value=value.String("FOO"),
                 label="POST1 LABEL")
    model.create("post2", value=ListOfInt(),
                 params=action.Param("param1", value.Integer(),
                                     is_required=False),
                 desc="POST2 DESC")
    model.action("post3", ActionTest)

    def __init__(self, source):
        model.Model.__init__(self, source)
        self.toto = "spam"
        self.tata = 42
        self.titi = True
        self.tutu = DummyEnum.b


@register
class InlineModel(model.Model):
    model.identity('test.inline')
    model.attribute("spam", value.Integer(),
                    getter.model_getattr())

    def init(self):
        self.spam = 44


@register
class StructModelTest(model.Model):
    model.identity("test.structs")
    model.attribute("dummy1", value.Struct(),
                    getter=getter.model_getattr())
    model.attribute("dummy2", value.Struct(),
                    getter=getter.model_getattr())
    model.attribute("dummy3", value.Struct(),
                    getter=getter.model_getattr())

    model.meta("model-meta", "METAVALUE", "METASCHEME")
    model.item_meta("dummy1", "item-meta", "METAVALUE")

    def __init__(self, source):
        model.Model.__init__(self, source)
        self.dummy1 = DummySnapshotable()
        self.dummy2 = DummySerializable()
        self.dummy3 = DummyParent()


@register
class ReferenceModel(model.Model):
    model.identity("test.refs")
    model.reference(call.model_call("_get_ref"))

    def _get_ref(self):
        return reference.Local("some", "place")


class DummyModel(model.Model):
    model.identity('test.int')
    model.attribute('value', value.Integer(),
                    effect.context_value('view'))


class TestApplicationJSON(common.TestCase):

    @defer.inlineCallbacks
    def check(self, obj, expected, exp_type=None,
              encoding="UTF8", verbose=False, **kwargs):
        doc = document.WritableDocument("application/json",
                                        encoding=encoding)
        ctx = DummyContext(("ROOT", ), ("root", ))
        fmt = "verbose" if verbose else "compact"
        yield document.write(doc, obj, context=ctx, format=fmt, **kwargs)
        data = doc.get_data()
        self.assertTrue(isinstance(data, str))
        struct = json.loads(data, encoding=encoding)
        if exp_type is not None:
            self.assertTrue(isinstance(struct, exp_type))
        if expected != struct:
            path, msg = deep_compare(expected, struct)
            expected_str = StringIO.StringIO()
            result_str = StringIO.StringIO()
            pprint.pprint(expected, stream=expected_str)
            pprint.pprint(struct, stream=result_str)
            self.fail("ERROR in %s: %s\nEXPECTED:\n%s\nRESULT:\n%s"
                      % (path, msg, expected_str.getvalue(),
                         result_str.getvalue()))
        defer.returnValue(data)

    def vcheck(self, obj, expected, exp_type=None, encoding="UTF8"):
        return self.check(obj, expected, exp_type=exp_type,
                          encoding=encoding, verbose=True)

    @defer.inlineCallbacks
    def testVerboseactModelWriter(self):
        rm = RootModelTest(object())

        exp = {u"identity": u"test.root",
               u"items":
               {u"toto": {u"label": u"TOTO LABEL",
                          u"desc": u"TOTO DESC",
                          u"readable": True,
                          u"value": u"spam",
                          u'metadata': [{u'name': u'json',
                                         u'value': u'attribute'}],
                          u"href": u"root/toto",
                          u"info": {u"type": u"string"}},
                u"tata": {u"label": u"TATA LABEL",
                          u"href": u"root/tata",
                          u'metadata': [{u'name': u'json',
                                         u'value': u'attribute'}],
                          u"writable": True,
                          u"info": {u"type": u"integer"}},
                u"titi": {u"desc": u"TITI DESC",
                          u"value": True,
                          u"readable": True,
                          u"writable": True,
                          u'metadata': [{u'name': u'json',
                                         u'value': u'attribute'}],
                          u"href": u"root/titi",
                          u"info": {u"type": u"boolean",
                                    u"options":
                                    [{u"label": u"True", u"value": True},
                                     {u"label": u"False", u"value": False}],
                                    u"restricted": True}},
                u"tutu": {u"value": u"B!",
                          u"href": u"root/tutu",
                          u"readable": True,
                          u'metadata': [{u'name': u'json',
                                         u'value': u'attribute'}],
                          u"info": {u"type": u"string",
                                    u"options":
                                    [{u"label": u"A", u"value": u"A"},
                                     {u"label": u"B!", u"value": u"B!"}],
                                    u"restricted": True}},
                u"tete": {u"value": u"root/test/tete",
                          u'metadata': [{u'name': u'json',
                                         u'value': u'attribute'}],
                          u"href": u"root/tete",
                          u"readable": True,
                          u"info": {u"type": u"reference"}},
                u"structs": {u"href": u"root/structs"},
                u'inline': {u'href': u'root/inline',
                            u'metadata': [{u'name': u'json',
                                           u'value': u'render-inline'}]},
                u"refs": {u"href": u"root/refs"}},
               u"actions":
               {u"del": {u"label": u"DEL LABEL",
                         u"desc": u"DEL DESC",
                         u"href": u"root/_del",
                         u"category": u"delete",
                         u"idempotent": True,
                         u"method": u"POST", # given by the context
                         u"result": {u"type": u"model"}},
                u"post1": {u"label": u"POST1 LABEL",
                           u"href": u"root/_post1",
                           u"category": u"create",
                           u"method": u"POST", # given by the context
                           u"params": {u"value":
                                       {u"required": True,
                                        u"info": {u"default": u"FOO",
                                                  u"type": u"string"}}},
                           u"result": {u"type": u"model"}},
                u"post2": {u"desc": u"POST2 DESC",
                           u"category": u"create",
                           u"href": u"root/_post2",
                           u"method": u"POST",
                           u"params":
                           {u"value": {u"required": True,
                                       u"info": {u"label": u"List Of Int",
                                                 u"desc": u"List of integers",
                                                 u"type": u"collection",
                                                 u"max_size": 3,
                                                 u"min_size": 1,
                                                 u"ordered": True,
                                                 u"allowed":
                                                 [{u"type": u"integer"}],
                                                 u"metadata":
                                                 [{u"name": u"type-meta",
                                                   u"value": u"METAVALUE"}]}},
                            u"param1": {u"required": False,
                                        u"info": {u"type": u"integer"}}},
                           u"result": {u"type": u"model"}},
                u"post3": {u"label": u"Test Action",
                           u"desc": u"Test action description",
                           u"href": u"root/_post3",
                           u"category": u"command",
                           u"method": u"POST",
                           u"params": {u"param1":
                                       {u"label": u"PARAM1 LABEL",
                                        u"required": True,
                                        u"info": {u"type": u"integer"}},
                                       u"param2":
                                       {u"desc": u"PARAM2 DESC",
                                        u"required": True,
                                        u"info": {u"type": u"integer"}}},
                           u"metadata": [{u"name": u"action-meta",
                                          u"value": u"METAVALUE"}]}}}
        yield self.vcheck(rm, exp)

        item = yield rm.fetch_item("toto")
        toto = yield item.fetch()

        exp = {u"identity": u"test.root.toto",
               u"name": u"toto",
               u"label": u"TOTO LABEL",
               u"desc": u"TOTO DESC",
               u"readable": True,
               u"value": u"spam",
               u"info": {u"type": u"string"},
               u"actions":
               {u"get": {u"category": u"retrieve",
                         u"href": u"root/_get",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"result": {u"type": u"string"}}}}
        yield self.vcheck(toto, exp)

        item = yield rm.fetch_item("tata")
        tata = yield item.fetch()

        exp = {u"identity": u"test.root.tata",
               u"label": u"TATA LABEL",
               u"name": u"tata",
               u"writable": True,
               u"info": {u"type": u"integer"},
               u"actions":
               {u"set": {u"category": u"update",
                         u"href": u"root/_set",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"params":
                         {u"value":
                          {u"info": {u"type": u"integer"},
                           u"required": True}},
                         u"result":
                         {u"type": u"integer"}}}}
        yield self.vcheck(tata, exp)

        item = yield rm.fetch_item("titi")
        titi = yield item.fetch()

        exp = {u"identity": u"test.root.titi",
               u"name": u"titi",
               u"desc": u"TITI DESC",
               u"readable": True,
               u"writable": True,
               u"value": True,
               u"info":
               {u"type": u"boolean",
                u"options":
                [{u"label": u"True", u"value": True},
                 {u"label": u"False", u"value": False}],
                u"restricted": True},
               u"actions":
               {u"get": {u"category": u"retrieve",
                         u"href": u"root/_get",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"result":
                         {u"type": u"boolean",
                          u"options":
                          [{u"label": u"True", u"value": True},
                           {u"label": u"False", u"value": False}],
                          u"restricted": True}},
                u"set": {u"category": u"update",
                         u"href": u"root/_set",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"params":
                         {u"value":
                          {u"required": True,
                           u"info":
                           {u"type": u"boolean",
                            u"options":
                            [{u"label": u"True", u"value": True},
                             {u"label": u"False", u"value": False}],
                            u"restricted": True}}},
                         u"result": {u"type": u"boolean",
                                     u"options":
                                     [{u"label": u"True", u"value": True},
                                      {u"label": u"False", u"value": False}],
                                     u"restricted": True}}}}

        yield self.vcheck(titi, exp)

        item = yield rm.fetch_item("tutu")
        tutu = yield item.fetch()

        exp = {u"identity": u"test.root.tutu",
               u"name": u"tutu",
               u"readable": True,
               u"value": u"B!",
               u"info": {u"type": u"string",
                         u"options":
                         [{u"label": u"A", u"value": u"A"},
                          {u"label": u"B!", u"value": u"B!"}],
                         u"restricted": True},
               u"actions":
               {u"get": {u"category": u"retrieve",
                         u"href": u"root/_get",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"result": {u"type": u"string",
                                     u"options":
                                     [{u"label": u"A", u"value": u"A"},
                                      {u"label": u"B!", u"value": u"B!"}],
                                     u"restricted": True}}}}
        yield self.vcheck(tutu, exp)

        item = yield rm.fetch_item("tete")
        tete = yield item.fetch()

        exp = {u"identity": u"test.root.tete",
               u"name": u"tete",
               u"readable": True,
               u"value": u"root/test/tete",
               u"info": {u"type": u"reference"},
               u"actions":
               {u"get": {u"category": u"retrieve",
                         u"href": u"root/_get",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"result": {u"type": u"reference"}}}}
        yield self.vcheck(tete, exp)

        item = yield rm.fetch_item("structs")
        structs = yield item.fetch()

        exp = {u"identity": u"test.structs",
               u"name": u"structs",
               u"items":
               {u"dummy1": {u"href": u"root/dummy1",
                            u"info": {u"type": u"struct"},
                            u"readable": True,
                            u"value": {u"toto": 3.14,
                                       u"tata": u"",
                                       u"titi": None,
                                       u"tutu": u"áéíóú"},
                            u"metadata": [{u"name": u"item-meta",
                                           u"value": u"METAVALUE"},
                                          {u'name': u'json',
                                           u'value': u'attribute'}]},
                u"dummy2": {u"href": u"root/dummy2",
                            u"info": {u"type": u"struct"},
                            u"readable": True,
                            u'metadata': [{u'name': u'json',
                                           u'value': u'attribute'}],
                            u"value": {u".type": u"json-dummy",
                                       u"toto": 1,
                                       u"tata": u"spam",
                                       u"titi": True,
                                       u"tutu": u"áéíóú",
                                       u"tete": ""}},
                u"dummy3": {u"href": u"root/dummy3",
                            u"info": {u"type": u"struct"},
                            u'metadata': [{u'name': u'json',
                                           u'value': u'attribute'}],
                            u"readable": True,
                            u"value": {u"a": {u"value": 1},
                                       u"b": {u"value": 2}}}},
               u"metadata": [{u"name": u"model-meta",
                              u"value": u"METAVALUE",
                              u"scheme": u"METASCHEME"}]}
        yield self.vcheck(structs, exp)

        item = yield structs.fetch_item("dummy1")
        dummy1 = yield item.fetch()

        exp = {u"identity": u"test.structs.dummy1",
               u"name": u"dummy1",
               u"info": {u"type": u"struct"},
               u"readable": True,
               u"value": {u"toto": 3.14,
                          u"tata": "",
                          u"titi": None,
                          u"tutu": u"áéíóú"},
               u"actions":
               {u"get": {u"category": u"retrieve",
                         u"href": u"root/_get",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"result": {u"type": u"struct"}}}}
        yield self.vcheck(dummy1, exp)

        item = yield structs.fetch_item("dummy2")
        dummy2 = yield item.fetch()

        exp = {u"identity": u"test.structs.dummy2",
               u"name": u"dummy2",
               u"readable": True,
               u"info": {u"type": u"struct"},
               u"value": {u".type": u"json-dummy",
                          u"toto": 1,
                          u"tata": u"spam",
                          u"titi": True,
                          u"tutu": u"áéíóú",
                          u"tete": u""},
               u"actions":
               {u"get": {u"category": u"retrieve",
                         u"href": u"root/_get",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"result": {u"type": u"struct"}}}}
        yield self.vcheck(dummy2, exp)

        item = yield structs.fetch_item("dummy3")
        dummy3 = yield item.fetch()

        exp = {u"identity": u"test.structs.dummy3",
               u"name": u"dummy3",
               u"readable": True,
               u"info": {u"type": u"struct"},
               u"value": {u"a": {u"value": 1}, u"b": {u"value": 2}},
               u"actions":
               {u"get": {u"category": u"retrieve",
                         u"href": u"root/_get",
                         u"idempotent": True,
                         u"method": u"POST",
                         u"result": {u"type": u"struct"}}}}
        yield self.vcheck(dummy3, exp)

        item = yield rm.fetch_item("refs")
        structs = yield item.fetch()

        exp = {u"identity": u"test.refs",
               u"name": u"refs",
               u"href": u"root/some/place"}
        yield self.vcheck(structs, exp)

    @defer.inlineCallbacks
    def testErrorWriter(self):
        K = DummyError
        t = ErrorTypes.generic
        yield self.check(K(t, None, None, None, None, None),
                         {u"type": u"error",
                          u"error": u"generic"})
        yield self.check(K(t, 42, None, None, None, None),
                         {u"type": u"error",
                          u"error": u"generic",
                          u"code": 42})
        yield self.check(K(t, None, "spam", None, None, None),
                         {u"type": u"error",
                          u"error": u"generic",
                          u"message": u"spam"})
        yield self.check(K(t, 42, "spam", None, None, None),
                         {u"type": u"error",
                          u"error": u"generic",
                          u"code": 42,
                          u"message": u"spam"})
        yield self.check(K(t, None, None, ["a", "b"], None, None),
                         {u"type": u"error",
                          u"error": u"generic",
                          u"subjects": [u"a", u"b"]})
        yield self.check(K(t, None, None, None, {"a": "spam"}, None),
                         {u"type": u"error",
                          u"error": u"generic",
                          u"reasons": {u"a": u"spam"}})

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
                         {u"type": u"reference", u"href": u"root/some/place"})

    @defer.inlineCallbacks
    def testCompactModelWriter(self):
        rm = RootModelTest(object())
        yield self.check(rm, {u"structs": u"root/structs",
                              u"refs": u"root/refs",
                              u"tata": None,
                              u"toto": u"spam",
                              u"titi": True,
                              u"tutu": u"B!",
                              u"inline": {u"spam": 44},
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
                                   u"dummy2": {u".type": u"json-dummy",
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
        yield self.check(dummy2, {u".type": u"json-dummy",
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
        # some json implemention gives non-unicode empty strings
        yield self.check("", u"", (unicode, str))
        yield self.check(u"", u"", (unicode, str))
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
                                {u".type": u"json-dummy",
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
                         {u"toto": {u".type": u"json-dummy",
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
