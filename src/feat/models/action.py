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

from feat.common import defer, annotate, container
from feat.models import utils, meta as models_meta

from feat.models.interface import *
from feat.models.interface import IValidator, IAspect, IActionFactory


meta = models_meta.meta


def label(label):
    """
    Annotates the default label of the action being defined
    if not specified by its aspect.
    @param label: the label of the action.
    @type label: str or unicode
    """
    _annotate("label", label)


def desc(desc):
    """
    Annotates the default description of the action being defined
    if not specified by its aspect.
    @param desc: the description of the action.
    @type desc: str or unicode
    """
    _annotate("desc", desc)


def category(category):
    """
    Annotates the category of the action being defined.
    @param category: the action category.
    @type category: ActionCategories
    """
    _annotate("category", category)


def is_idempotent(is_idempotent=True):
    """
    Annotate the action being defined as being idempotent,
    meaning performing the action multiple time with the same value
    and parameters will have the same result as calling it once.
    """
    _annotate("is_idempotent", is_idempotent=is_idempotent)


def value(value_info):
    """
    Annotate the value information of the action being defined.
    @param value_info: the value information of the action.
    @type value_info: value.IValueInfo
    """
    _annotate("value", value_info)


def param(name, info, is_required=True, label=None, desc=None):
    """
    Annotate the value information of the action being defined.
    @param name: name of the parameter defined (ASCII encoded).
    @type name: str
    @param info: the paramter value information.
    @type info: value.IValueInfo
    @param is_required: if the parameter is required or optional.
    @type is_required: bool
    @param label: the parameter label or None.
    @type label: str or unicode or None
    @param desc: the parameter description or None.
    @type desc: str or unicode or None
    """
    _annotate("param", name, info, is_required=is_required,
              label=label, desc=desc)


def result(result_info):
    """
    Annotate the result information of the action being defined.
    @param result_info: the result information of the action.
    @type result_info: value.IValueInfo
    """
    _annotate("result", result_info)


def effect(effect):
    """
    Annotate an effect of the action being defined.
    @param effect: an effect, see feat.models.call for effect information.
    @type effect: callable
    """
    _annotate("effect", effect)


def enabled(is_enabled):
    """
    Annotate the availability of the action being defined.
    @param is_enabled: a boolean or an effect,
                       see feat.models.call for effect information..
    @type is_enabled: bool or callable
    """
    _annotate("enabled", is_enabled)


def _annotate(name, *args, **kwargs):
    method_name = "annotate_" + name
    annotate.injectClassCallback(name, 4, method_name, *args, **kwargs)


class ActionParam(object):
    """Defines an action parameter."""

    implements(IActionParam)

    def __init__(self, name, info, is_required=True, label=None, desc=None):
        self._name = str(name)
        self._label = unicode(label) if label is not None else None
        self._desc = unicode(desc) if desc is not None else None
        self._info = info
        self._is_required = is_required

    ### IActionParam ###

    @property
    def name(self):
        return self._name

    @property
    def label(self):
        return self._label

    @property
    def desc(self):
        return self._desc

    @property
    def info(self):
        return self._info

    @property
    def is_required(self):
        return self._is_required


class MetaAction(type(models_meta.Metadata)):

    implements(IActionFactory)

    @staticmethod
    def new(name, category, effects=[],
            value_info=None, result_info=None,
            is_idempotent=True, enabled=True):
        cls_name = utils.mk_class_name(name, "Action")
        cls = MetaAction(cls_name, (Action, ), {"__slots__": ()})
        cls.annotate_category(category)
        cls.annotate_value(value_info)
        cls.annotate_result(result_info)
        cls.annotate_is_idempotent(is_idempotent)
        cls.annotate_enabled(enabled)
        for e in effects:
            cls.annotate_effect(e)
        return cls


class Action(models_meta.Metadata):
    """Action definition instantiated for a specific model and aspect."""

    __metaclass__ = MetaAction
    __slots__ = ("model", "aspect")

    implements(IModelAction)

    _category = None
    _is_idempotent = None
    _value_info = None
    _result_info = None
    _enabled = True
    _parameters = container.MroDict("_mro_parameters")
    _effects = container.MroList("_mro_effects")

    def __init__(self, model, aspect=None):
        """Initialize amodel's action.
        @param model: the model the action belong to.
        @type model: IModel
        """
        self.model = IModel(model)
        self.aspect = IAspect(aspect) if aspect is not None else None

    ### IModelAction ###

    @property
    def name(self):
        return self.aspect.name if self.aspect is not None else None

    @property
    def label(self):
        if self.aspect is not None and self.aspect.label is not None:
            return self.aspect.label
        return self._label

    @property
    def desc(self):
        if self.aspect is not None and self.aspect.desc is not None:
            return self.aspect.desc
        return self._desc

    @property
    def category(self):
        return self._category

    @property
    def is_idempotent(self):
        return self._is_idempotent

    @property
    def value_info(self):
        return self._value_info

    @property
    def parameters(self):
        return self._parameters.values()

    @property
    def result_info(self):
        return self._result_info

    def fetch_enabled(self):
        enabled = self._enabled
        if not callable(enabled):
            return defer.succeed(bool(enabled))
        # By default the key is the action name
        return enabled(None, self._mk_ctx())

    def perform(self, *args, **kwargs):
        parameters = self._parameters # Only once cause it is costly
        value = None
        d = defer.Deferred()

        try:

            params = set(kwargs.keys())
            expected = set(parameters.keys())
            required = set([p.name for p in parameters.itervalues()
                            if p.is_required])

            if not required <= params:
                raise TypeError("Action %s require parameters: %s"
                                % (self.name, ", ".join(required)))

            if not params <= expected:
                raise TypeError("Action %s expect only parameters: %s"
                                % (self.name, ", ".join(expected)))

            validated = {}
            for param_name, param_value in kwargs.iteritems():
                info = parameters[param_name].info
                validated[param_name] = IValidator(info).validate(param_value)

            for param in parameters.itervalues():
                if not param.is_required:
                    info = param.info
                    if param.name not in validated and info.use_default:
                        validated[param.name] = info.default

            if self._value_info is None:
                if args:
                    # The action do not allow values
                    raise TypeError("Action %s do not allow values"
                                    % self.name)
            else:
                if not args:
                    raise TypeError("No value specified")

                if len(args) > 1:
                    raise TypeError("Only one value allowed")

                value = args[0]
                d.addCallback(IValidator(self._value_info).validate)

            # We use the model name instead of the action name as key
            context = self._mk_ctx(self.model.name)

            for effect in self._effects:
                d.addCallback(effect, context, **validated)

            if self._result_info is not None:
                d.addCallback(IValidator(self._result_info).validate)
            else:
                d.addCallback(defer.override_result, None)

        except ValueError:
            return defer.fail()

        except TypeError:
            return defer.fail()

        else:

            d.callback(value)
            return d

    ### private ###

    def _mk_ctx(self, key=None):
        return {"model": self.model,
                "view": self.model.view,
                "action": self,
                "key": key or self.name}

    ### annotations ###

    @classmethod
    def annotate_label(cls, label):
        """@see: feat.models.action.label"""
        cls._label = _validate_optstr(label)

    @classmethod
    def annotate_desc(cls, desc):
        """@see: feat.models.action.desc"""
        cls._desc = _validate_optstr(desc)

    @classmethod
    def annotate_category(cls, category):
        """@see: feat.models.action.category"""
        cls._category = ActionCategory(category)

    @classmethod
    def annotate_is_idempotent(cls, is_idempotent=True):
        """@see: feat.models.action.is_idempotent"""
        cls._is_idempotent = bool(is_idempotent)

    @classmethod
    def annotate_value(cls, value_info):
        """@see: feat.models.action.value"""
        cls._value_info = _validate_value_info(value_info)

    @classmethod
    def annotate_result(cls, result_info):
        """@see: feat.models.action.result"""
        cls._result_info = _validate_value_info(result_info)

    @classmethod
    def annotate_enabled(cls, is_enabled):
        """@see: feat.models.action.enabled"""
        # We keep it in a tuple to prevent it to be bound if it's a function
        cls._enabled = _validate_effect(is_enabled)

    @classmethod
    def annotate_param(cls, name, info, is_required=True,
                           label=None, desc=None):
        """@see: feat.models.action.parameter"""
        name = _validate_str(name)
        param = ActionParam(name, info, is_required=is_required,
                            label=label, desc=desc)
        cls._parameters[name] = param

    @classmethod
    def annotate_effect(cls, effect):
        """@see: feat.models.action.effect"""
        cls._effects.append(effect)


### private ###


def _validate_str(value):
    return unicode(value)


def _validate_optstr(value):
    return unicode(value) if value is not None else None


def _validate_effect(effect):
    if isinstance(effect, types.FunctionType):
        return staticmethod(effect)
    return effect


def _validate_value_info(info):
    return IValueInfo(info) if info is not None else None
