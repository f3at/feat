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

from feat.common import defer, annotate
from feat.models import model, action, utils, effect, value as value_module

from feat.models.interface import ActionCategories, IAttribute, NotSupported
from feat.models.interface import IValueInfo


def value(value_info):
    annotate.injectClassCallback("value", 3, "annotate_value", value_info)


class MetaAttribute(type(model.AbstractModel)):

    @staticmethod
    def new(identity, value_info, getter=None, setter=None,
            deleter=None, meta=None):
        cls_name = utils.mk_class_name(identity, "Attribute")
        cls = MetaAttribute(cls_name, (_DynAttribute, ), {"__slots__": ()})
        cls.annotate_identity(identity)
        cls.annotate_value(value_info)
        cls.apply_class_meta(meta)

        if getter is not None:

            Action = action.MetaAction.new("get." + identity,
                                           ActionCategories.retrieve,
                                           effects=[getter],
                                           result_info=value_info,
                                           is_idempotent=True)

            cls.annotate_action(u"get", Action)

        if setter is not None:

            def _set_attribute(value, context):
                d = setter(value, context)
                # attribute setter return the validate value
                d.addCallback(defer.override_result, value)
                return d

            Action = action.MetaAction.new("set." + identity,
                                           ActionCategories.update,
                                           effects=[_set_attribute],
                                           value_info=value_info,
                                           result_info=value_info,
                                           is_idempotent=True)

            cls.annotate_action(u"set", Action)

        if deleter is not None:

            Action = action.MetaAction.new('delete.' + identity,
                                           ActionCategories.delete,
                                           effects=[
                                               deleter,
                                               effect.static_value('')],
                                           result_info=value_module.String(),
                                           is_idempotent=True)
            cls.annotate_action(u"del", Action)


        return cls


class Attribute(model.AbstractModel,
                model.NoChildrenMixin, model.StaticActionsMixin):

    __slots__ = ()

    implements(IAttribute)

    _model_value_info = None

    ### IAttribute ###

    @property
    def value_info(self):
        return self._model_value_info

    @property
    def is_readable(self):
        return u"get" in self._action_items

    @property
    def is_writable(self):
        return u"set" in self._action_items

    @property
    def is_deletable(self):
        return u"del" in self._action_items

    def fetch_value(self):

        def perform(action):
            if action is None:
                raise NotSupported("Attribute %s not readable" % self.name)
            return action.perform()

        d = self.fetch_action(u"get")
        d.addCallback(perform)
        return d

    def update_value(self, value):

        def perform(action):
            if action is None:
                raise NotSupported("Attribute %s not writable" % self.name)
            return action.perform(value)

        d = self.fetch_action(u"set")
        d.addCallback(perform)
        return d

    def delete_value(self):

        def perform(action):
            if action is None:
                raise NotSupported("Attribute %s not deletable" % self.name)
            return action.perform()

        d = self.fetch_action(u"del")
        d.addCallback(perform)
        return d

    ### annotations ###

    @classmethod
    def annotate_value(cls, value_info):
        """@see: feat.models.attribute.value"""
        cls._model_value_info = IValueInfo(value_info)


class _DynAttribute(Attribute):

    __slots__ = ("parent", )

    ### IModel ###

    def initiate(self, aspect=None, view=None, parent=None, officer=None):
        self.parent = parent
        return Attribute.initiate(self, aspect=aspect, view=view,
                                  parent=parent, officer=officer)

    ### IContextMaker ###

    def make_context(self, key=None, view=None, action=None):
        model = self.parent or self
        return {"model": model,
                "source": model.source,
                "view": model.view,
                "officer": model.officer,
                "view": model.view,
                "key": unicode(key) if key is not None else self.name,
                "action": action}
