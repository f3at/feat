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

from feat.common import defer, serialization, error, log
from feat.common.serialization import json as feat_json
from feat.common.container import AsyncDict
from feat.web import document

from feat.models.interface import IModel, IReference
from feat.models.interface import IErrorPayload
from feat.models.interface import IActionPayload, IMetadata, IAttribute
from feat.models.interface import IValueCollection, IValueOptions, IValueRange
from feat.models.interface import IEncodingInfo, ValueTypes
from feat.models.interface import Unauthorized

MIME_TYPE = "application/json"


class ActionPayload(dict):
    implements(IActionPayload)


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
    args = (context, result)
    return item.fetch().addCallbacks(render_attribute, filter_errors,
                                     callbackArgs=args, errbackArgs=args)


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
        if attr.value_info.value_type is not ValueTypes.binary:
            d = attr.fetch_value()
            d.addCallback(render_value, subcontext)
            result.add("value", d)
    return result.wait()


def filter_errors(failure, context, result):
    failure.trap(Unauthorized)
    return result and result.wait()


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
    if IEncodingInfo.providedBy(value):
        encinfo = IEncodingInfo(value)
        result.add_if_not_none("mimetype", encinfo.mime_type)
        result.add_if_not_none("encoding", encinfo.encoding)
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
    if render_as_list(model):
        return render_model_as_list(model, context)

    result = AsyncDict()
    if model.reference:
        result.add_result("href", model.reference, "resolve", context)
    d = model.fetch_items()
    d.addCallback(render_compact_items, context, result)
    return d


def render_compact_items(items, context, result):
    for item in items:
        if render_inline(item):
            d = item.fetch()
            d.addCallback(render_inline_model, context)
            result.add(item.name, d)
        elif iattribute_meta(item) and not prevent_inline(item):
            d = item.fetch()
            d.addCallback(render_compact_attribute, item, context)
            result.add(item.name, d)
        elif item.reference is not None:
            result.add(item.name, item.reference.resolve(context))
    return result.wait()


def _parse_meta(meta_items):
    return [i.strip() for i in meta_items.value.split(",")]


def get_parsed_meta(meta):
    if not IMetadata.providedBy(meta):
        return []
    parsed = [_parse_meta(i) for i in meta.get_meta('json')]
    return parsed


def iattribute_meta(meta):
    parsed = get_parsed_meta(meta)
    return ['attribute'] in parsed


def render_inline(meta):
    parsed = get_parsed_meta(meta)
    return ['render-inline'] in parsed


def render_as_list(meta):
    parsed = get_parsed_meta(meta)
    return ['render-as-list'] in parsed


def prevent_inline(meta):
    parsed = get_parsed_meta(meta)
    return ['prevent-inline'] in parsed


def render_compact_attribute(submodel, item, context):
    attr = IAttribute(submodel)
    if attr.value_info.value_type is ValueTypes.binary:
        if item.reference is not None:
            return item.reference.resolve(context)
    elif attr.is_readable:
        d = attr.fetch_value()
        d.addCallback(render_value, context)
        return d


def filter_model_errors(failure, item, context):
    failure.trap(Unauthorized)
    if item.reference is not None:
        return item.reference.resolve(context)
    return failure


def render_json(data, doc):
    if doc.encoding == 'nested-json':
        doc.write(data)
    else:
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


class NestedJson(document.BaseDocument):
    '''
    This is an implementation used to represent nested documents which
    are rendered inline. It is used in CustomJSONEncoder to injects
    preserialized parts of resulting json into the structure.
    '''

    implements(document.IWritableDocument)

    def __init__(self):
        document.BaseDocument.__init__(self, MIME_TYPE, 'nested-json')
        self._data = None

    def get_data(self):
        return self._data

    ### IWriter ###

    def write(self, data):
        self._data = data

    def writelines(self, sequence):
        raise NotImplementedError("This should not be used for NestedJson")


def render_inline_model(obj, context, *args, **kwargs):
    obj = IModel(obj)

    doc = NestedJson()
    d = document.write(doc, obj, context=context)
    d.addCallback(defer.override_result, doc)
    return d


def render_model_as_list(obj, context):

    def got_items(items):
        defers = list()
        for item in items:
            d = item.fetch()
            d.addCallbacks(render_inline_model, filter_model_errors,
                           callbackArgs=(context, ),
                           errbackArgs=(item, context))
            defers.append(d)
        return defer.DeferredList(defers, consumeErrors=True)

    d = obj.fetch_items()
    d.addCallback(got_items)
    d.addCallback(unpack_deferred_list_result)
    d.addCallback(list)
    return d


def unpack_deferred_list_result(results):

    for successful, result in results:
        if not successful:
            error.handle_failure(None, result, "Failed rendering inline model")
            continue
        yield result


def write_reference(doc, obj, *args, **kwargs):
    context = kwargs["context"]
    result = obj.resolve(context)
    render_json({u"type": u"reference", u"href": result}, doc)


def write_error(doc, obj, *args, **kwargs):
    result = {}
    result[u"type"] = u"error"
    result[u"error"] = unicode(obj.error_type.name)
    if obj.error_code is not None:
        result[u"code"] = int(obj.error_code)
    if obj.message is not None:
        result[u"message"] = obj.message
    if obj.subjects is not None:
        result[u"subjects"] = list(obj.subjects)
    if obj.reasons:
        result[u"reasons"] = dict([k, str(v)]
                                   for k, v in obj.reasons.iteritems())
    if obj.debug is not None:
        result[u"debug"] = obj.debug
    if obj.stamp:
        result[u"stamp"] = obj.stamp
        log.debug('application/json',
                  'Wrote error response with debug stamp: %s', obj.stamp)
        log.debug('application/json', 'Error: %s', result[u'error'])
        if obj.message:
            log.debug('application/json', 'Message: %s', obj.message)
    render_json(result, doc)


def write_anything(doc, obj, *args, **kwargs):
    render_json(obj, doc)


def read_action(doc, *args, **kwargs):
    data = doc.read()
    if not data:
        return ActionPayload()

    try:
        params = json.loads(data)
    except ValueError, e:
        raise document.DocumentFormatError("Invalid JSON document: %s"
                                           % (e, ))

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
        if isinstance(obj, NestedJson):
            # models marked with render-inline are rendered into a separate
            # IWritableDocument instance, which is here injected into its
            # placeholder in the resulting document
            return obj.get_data()
        return json.JSONEncoder.default(self, obj)
