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

from feat.common import defer, serialization
from feat.common.serialization import json as feat_json
from feat.models import reference
from feat.web import document

from feat.models.interface import *

MIME_TYPE = "application/json"


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


@defer.inlineCallbacks
def render_items(obj, context):
    result = {}
    items = yield obj.fetch_items()
    for item in items:
        result[item.name] = yield render_item(item, context)
    defer.returnValue(result)


@defer.inlineCallbacks
def render_actions(obj, context):
    result = {}
    actions = yield obj.fetch_actions()
    for action in actions:
        result[action.name] = yield render_action(action, context)
    defer.returnValue(result)


@defer.inlineCallbacks
def render_item(item, context):
    result = {}
    if item.label is not None:
        result["label"] = item.label
    if item.desc is not None:
        result["desc"] = item.desc
    metadata = yield render_metadata(item)
    if metadata:
        result["metadata"] = metadata
    result["url"] = item.reference.resolve(context)
    defer.returnValue(result)


@defer.inlineCallbacks
def render_action(action, context):
    result = {}
    if action.label is not None:
        result["label"] = action.label
    if action.desc is not None:
        result["desc"] = action.desc
    metadata = yield render_metadata(action)
    if metadata:
        result["metadata"] = metadata
    if action.result_info is not None:
        result["result"] = render_value(action.result_info)
    params = render_params(action.parameters)
    if params:
        result["params"] = params
    result["url"] = action.reference.resolve(context)
    defer.returnValue(result)


def render_value(value):
    result = {}
    result["type"] = value.value_type.name
    if value.use_default:
        result["default"] = value.default
    if value.label is not None:
        result["label"] = value.label
    if value.desc is not None:
        result["desc"] = value.desc
    metadata = render_metadata(value)
    if metadata:
        result["metadata"] = metadata
    if IValueCollection.providedBy(value):
        coll = IValueCollection(value)
        result["allowed"] = [render_value(v) for v in coll.allowed_types]
        result["ordered"] = coll.is_ordered
        result["multiple"] = coll.allow_multiple
    if IValueRange.providedBy(value):
        vrange = IValueRange(value)
        result["minimum"] = vrange.minimum
        result["maximum"] = vrange.maximum
        if vrange.increment is not None:
            result["increment"] = vrange.increment
    if IValueOptions.providedBy(value):
        options = IValueOptions(value)
        result["restricted"] = options.is_restricted
        result["options"] = [{"label": o.label, "value": o.value}
                             for o in options.iter_options()]
    return result


def render_params(params):
    return dict([(p.name, render_param(p)) for p in params])


def render_param(param):
    result = {}
    result["required"] = param.is_required
    result["value"] = render_value(param.value_info)
    if param.label is not None:
        result["label"] = param.label
    if param.desc is not None:
        result["desc"] = param.desc
    return result


@defer.inlineCallbacks
def write_model(doc, obj, *args, **kwargs):
    context = kwargs["context"]
    result = {}
    metadata = render_metadata(obj)
    items = yield render_items(obj, context)
    actions = yield render_actions(obj, context)
    if metadata:
        result["metadata"] = metadata
    if items:
        result["items"] = items
    if actions:
        result["actions"] = actions
    doc.write(json.dumps(result, indent=2))


def write_serializable(doc, obj, *args, **kwargs):
    serializer = feat_json.Serializer()
    data = serializer.convert(obj)
    doc.write(data)


def write_anything(doc, obj, *args, **kwargs):
    doc.write(unicode(obj))


document.register_writer(write_model, MIME_TYPE, IModel)
document.register_writer(write_serializable, MIME_TYPE,
                         serialization.ISerializable)
document.register_writer(write_anything, MIME_TYPE, None)
