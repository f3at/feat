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

from zope.interface import implements

from feat.common import defer, serialization
from feat.common.serialization import json as feat_json
from feat.web import document

from feat.models.interface import IModel, IReference, IErrorPayload
from feat.models.interface import IActionPayload, IMetadata, IAttribute
from feat.models.interface import IValueCollection, IValueOptions, IValueRange

MIME_TYPE = "application/json"


class ActionPayload(dict):
    implements(IActionPayload)


class AsyncDict(object):

    def __init__(self):
        self._values = []
        self._info = []

    def add_if_true(self, key, value):
        self.add(key, value, bool)

    def add_if_not_none(self, key, value):
        self.add(key, value, lambda v: v is not None)

    def add_result(self, key, value, method_name, *args, **kwargs):
        if not isinstance(value, defer.Deferred):
            value = defer.succeed(value)
        value.addCallback(self._call_value, method_name, *args, **kwargs)
        self.add(key, value)

    def add(self, key, value, condition=None):
        if not isinstance(value, defer.Deferred):
            value = defer.succeed(value)
        self._info.append((key, condition))
        self._values.append(value)

    def wait(self):
        d = defer.DeferredList(self._values, consumeErrors=True)
        d.addCallback(self._process_values)
        return d

    ### private ###

    def _process_values(self, param):
        return dict((k, v) for (s, v), (k, c) in zip(param, self._info)
                    if s and (c is None or c(v)))

    def _call_value(self, value, method_name, *args, **kwargs):
        return getattr(value, method_name)(*args, **kwargs)


def render_metadata(obj):
    result = []
    if IMetadata.providedBy(obj):
        metadata = IMetadata(obj)
        for metaitem in metadata.iter_meta():
            m = {"name": metaitem.name,
                 "value": metaitem.value}
            if metaitem.scheme is not None:
                m["scheme"] = metaitem.scheme
            result.append(m)
    return result


def render_model_items(model, context):
    return model.fetch_items().addCallback(render_items, context)


def render_items(items, context):
    result = AsyncDict()
    for item in items:
        result.add(item.name, render_item(item, context))
    return result.wait()


def render_model_actions(model, context):
    return model.fetch_actions().addCallback(render_actions, context)


def render_actions(actions, context):
    result = AsyncDict()
    for action in actions:
        result.add(action.name, render_action(action, context))
    return result.wait()


def render_item(item, context):
    result = AsyncDict()
    result.add_if_not_none("label", item.label)
    result.add_if_not_none("desc", item.desc)
    result.add_if_true("metadata", render_metadata(item))
    result.add_result("href", item.reference, "resolve", context)
    return item.fetch().addCallback(render_attribute, context, result)


def render_attribute(model, context, result=None):
    if not IAttribute.providedBy(model):
        return result and result.wait()
    result = result or AsyncDict()
    subcontext = context.descend(model)
    attr = IAttribute(model)
    result.add("info", render_value_info(attr.value_info))
    result.add_if_true("readable", attr.is_readable)
    result.add_if_true("writable", attr.is_writable)
    result.add_if_true("deletable", attr.is_deletable)
    if attr.is_readable:
        d = attr.fetch_value()
        d.addCallback(render_value, subcontext)
        result.add("value", d)
    return result.wait()


def render_action(action, context):
    result = AsyncDict()
    result.add_if_not_none("label", action.label)
    result.add_if_not_none("desc", action.desc)
    result.add_if_true("metadata", render_metadata(action))
    result.add("method", context.get_action_method(action).name)
    result.add_if_true("idempotent", bool(action.is_idempotent))
    result.add("category", action.category.name)
    result.add_result("href", action.reference, "resolve", context)
    if action.result_info is not None:
        result.add("result", render_value_info(action.result_info))
    if action.parameters:
        result.add("params", render_params(action.parameters))
    return result.wait()


def render_value_info(value):
    result = AsyncDict()
    result.add("type", value.value_type.name)
    if value.use_default:
        result.add("default", value.default)
    result.add_if_not_none("label", value.label)
    result.add_if_not_none("desc", value.desc)
    result.add_if_true("metadata", render_metadata(value))
    if IValueCollection.providedBy(value):
        coll = IValueCollection(value)
        allowed = [render_value_info(v) for v in coll.allowed_types]
        result.add("allowed", defer.join(*allowed))
        result.add("ordered", coll.is_ordered)
        result.add_if_not_none("min_size", coll.min_size)
        result.add_if_not_none("max_size", coll.max_size)
    if IValueRange.providedBy(value):
        vrange = IValueRange(value)
        result.add("minimum", vrange.minimum)
        result.add("maximum", vrange.maximum)
        result.add_if_not_none("increment", vrange.increment)
    if IValueOptions.providedBy(value):
        options = IValueOptions(value)
        result.add("restricted", options.is_restricted)
        result.add("options", [{"label": o.label, "value": o.value}
                               for o in options.iter_options()])
    return result.wait()


def render_params(params):
    result = AsyncDict()
    for param in params:
        result.add(param.name, render_param(param))
    return result.wait()


def render_param(param):
    result = AsyncDict()
    result.add("required", param.is_required)
    result.add("info", render_value_info(param.value_info))
    result.add_if_not_none("label", param.label)
    result.add_if_not_none("desc", param.desc)
    return result.wait()


def render_value(value, context):
    if IReference.providedBy(value):
        return value.resolve(context)
    return value


def render_verbose(model, context):
    result = AsyncDict()
    result.add("identity", model.identity)
    result.add_if_not_none("name", model.name)
    result.add_if_not_none("label", model.label)
    result.add_if_not_none("desc", model.desc)
    result.add_result("href", model.reference, "resolve", context)
    result.add_if_true("metadata", render_metadata(model))
    result.add_if_true("items", render_model_items(model, context))
    result.add_if_true("actions", render_model_actions(model, context))
    return render_attribute(model, context, result)


def render_compact_model(model, context):
    if IAttribute.providedBy(model):
        attr = IAttribute(model)
        if attr.is_readable:
            d = attr.fetch_value()
            d.addCallback(render_value, context)
            return d
        return defer.succeed(None)

    result = AsyncDict()
    if model.reference:
        result.add_result("href", model.reference, "resolve", context)
    d = model.fetch_items()
    d.addCallback(render_compact_items, context, result)
    return d


def render_compact_items(items, context, result):
    for item in items:
        d = item.fetch()
        d.addCallback(render_compact_submodel, item, context)
        result.add(item.name, d)
    return result.wait()


def render_compact_submodel(submodel, item, context):
    if not IAttribute.providedBy(submodel):
        if item.reference is not None:
            return item.reference.resolve(context)
    else:
        attr = IAttribute(submodel)
        if attr.is_readable:
            d = attr.fetch_value()
            d.addCallback(render_value, context)
            return d
    raise Exception("No compact value")


def render_json(data, doc):
    enc = CustomJSONEncoder(encoding=doc.encoding)
    doc.write(enc.encode(data))


def write_model(doc, obj, *args, **kwargs):
    context = kwargs["context"]

    verbose = "format" in kwargs and "verbose" in kwargs["format"]

    if verbose:
        d = render_verbose(obj, context)
    else:
        d = render_compact_model(obj, context)

    return d.addCallback(render_json, doc)


def write_reference(doc, obj, *args, **kwargs):
    context = kwargs["context"]
    result = obj.resolve(context)
    render_json({'href': result}, doc)


def write_error(doc, obj, *args, **kwargs):
    result = {}
    if obj.code is not None:
        result["code"] = obj.code
    if obj.message is not None:
        result["message"] = obj.message
    if obj.debug is not None:
        result["debug"] = obj.debug
    if obj.trace is not None:
        result["trace"] = obj.trace
    render_json(result, doc)


def write_anything(doc, obj, *args, **kwargs):
    render_json(obj, doc)


def read_action(doc, *args, **kwargs):
    data = doc.read()
    if not data:
        return ActionPayload()
    params = json.loads(data)
    if not isinstance(params, dict):
        return ActionPayload([(u"value", params)])
    return ActionPayload(params)


document.register_writer(write_model, MIME_TYPE, IModel)
document.register_writer(write_error, MIME_TYPE, IErrorPayload)
document.register_writer(write_reference, MIME_TYPE, IReference)
# document.register_writer(write_serializable, MIME_TYPE,
#                          serialization.ISerializable)
document.register_writer(write_anything, MIME_TYPE, None)

document.register_reader(read_action, MIME_TYPE, IActionPayload)


### private ###


class CustomJSONEncoder(json.JSONEncoder):

    def __init__(self, context=None, encoding=None):
        kwargs = {"indent": 2}
        if encoding is not None:
            kwargs["encoding"] = encoding
        json.JSONEncoder.__init__(self, **kwargs)
        self._serializer = feat_json.PreSerializer()

    def default(self, obj):
        if serialization.ISerializable.providedBy(obj):
            return self._serializer.convert(obj)
        if serialization.ISnapshotable.providedBy(obj):
            return self._serializer.freeze(obj)
        return json.JSONEncoder.default(self, obj)
