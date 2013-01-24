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

import sys
import types

from zope.interface import implements

from twisted.python.failure import Failure

from feat.common import error, defer, mro, annotate, container
from feat.models import utils, reference, meta as models_meta

from feat.models.interface import *
from feat.models.interface import IValidator, IAspect
from feat.models.interface import IActionFactory, IContextMaker


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


def value(value_info, label=None, desc=None):
    """
    Annotate the value information of the action being defined.
    @param value_info: the value parameter information.
    @type value_info: value.IValueInfo
    @param label: the parameter label or None.
    @type label: str or unicode or None
    @param desc: the parameter description or None.
    @type desc: str or unicode or None
    """
    _annotate("value", value_info, label=label, desc=desc)


def param(name, value_info, is_required=True, label=None, desc=None):
    """
    Annotate a parameter of the action being defined.
    @param name: name of the parameter defined.
    @type name: unicode or str
    @param value_info: the parameter value information.
    @type value_info: value.IValueInfo
    @param is_required: if the parameter is required or optional.
    @type is_required: bool
    @param label: the parameter label or None.
    @type label: str or unicode or None
    @param desc: the parameter description or None.
    @type desc: str or unicode or None
    """
    _annotate("param", name, value_info, is_required=is_required,
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


class Param(object):
    """Defines an action parameter."""

    implements(IActionParam)

    def __init__(self, name, value_info,
                 is_required=True, label=None, desc=None):
        self._name = unicode(name)
        self._label = _validate_optstr(label)
        self._desc = _validate_optstr(desc)
        self._value_info = IValueInfo(value_info)
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
    def value_info(self):
        return self._value_info

    @property
    def is_required(self):
        return self._is_required


class MetaAction(type(models_meta.Metadata)):

    implements(IActionFactory)

    @staticmethod
    def new(name, category, effects=None, params=None,
            value_info=None, result_info=None,
            is_idempotent=True, enabled=True):
        cls_name = utils.mk_class_name(name, "Action")
        cls = MetaAction(cls_name, (Action, ), {"__slots__": ()})
        cls.annotate_category(category)
        if value_info is not None:
            cls.annotate_value(value_info)
        if result_info is not None:
            cls.annotate_result(result_info)
        cls.annotate_is_idempotent(is_idempotent)
        cls.annotate_enabled(enabled)

        if params:
            if isinstance(params, Param):
                params = [params]
            for p in params:
                cls.annotate_param_instance(p)

        if effects:
            for e in effects:
                cls.annotate_effect(e)
        return cls


class Action(models_meta.Metadata, mro.DeferredMroMixin):
    """Action definition instantiated for a specific model and aspect."""

    __metaclass__ = MetaAction
    __slots__ = ("model", "aspect")

    implements(IModelAction)

    _label = None
    _desc = None
    _category = ActionCategories.command
    _is_idempotent = False
    _result_info = None
    _enabled = True
    _parameters = container.MroList("_mro_parameters")
    _effects = container.MroList("_mro_effects")

    ### class methods ###

    @classmethod
    def create(cls, model, aspect=None):
        a = cls(model)
        return a.initiate(aspect=aspect)

    ### public ###

    def __init__(self, model):
        """
        @param model: the model the action belong to.
        @type model: IModel
        """
        self.model = IModel(model)
        self.aspect = None

    ### virtual ###

    def init(self):
        """Override in sub-classes to initiate the action.
        All sub-classes init() methods are called in MRO order.
        Can return a deferred."""

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
    def reference(self):
        return reference.Action(self)

    @property
    def category(self):
        return self._category

    @property
    def is_idempotent(self):
        return self._is_idempotent

    @property
    def parameters(self):
        inverted_result = []
        already_added = set()
        for p in reversed(self._parameters):
            if p.name not in already_added:
                inverted_result.append(p)
                already_added.add(p.name)
        return list(reversed(inverted_result))

    @property
    def result_info(self):
        return self._result_info

    def initiate(self, aspect=None):
        self.aspect = IAspect(aspect) if aspect is not None else None
        d = self.call_mro("init")
        d.addCallback(defer.override_result, self)
        return d

    def fetch_enabled(self):
        enabled = self._enabled
        if not callable(enabled):
            return defer.succeed(bool(enabled))
        # By default the key is the action name
        maker = IContextMaker(self.model)
        context = maker.make_context(key=self.name, action=self)
        return enabled(None, context)

    def perform(self, *args, **kwargs):

        def raise_if_disabled(enabled, value):
            if not enabled:
                raise NotAvailable('Action %s is not enabled' % (self.name, ))
            return value

        def check_enabled(value):
            d = self.fetch_enabled()
            d.addCallback(raise_if_disabled, value)
            return d

        parameters = self.parameters # Only once cause it is costly
        value = None
        d = defer.Deferred()
        d.addCallback(check_enabled)
        try:
            if len(args) > 0:
                values = list(args)
                values += [kwargs[u"value"]] if u"value" in kwargs else []
                if len(values) > 1:
                    m = ("Action %s can only have one value: %s"
                         % (self.name, ", ".join([repr(v) for v in values])))
                    raise ParameterError(m, params=("value", ))
                if args:
                    kwargs[u"value"] = args[0]

            params = set(kwargs.keys())
            expected = set([p.name for p in parameters])
            required = set([p.name for p in parameters if p.is_required])

            if not required <= params:
                missings = required - params
                msg = ("Action %s is missing parameter(s): %s"
                       % (self.name, ", ".join(missings)))
                raise MissingParameters(msg, params=missings)

            if not params <= expected:
                unknown = params - expected
                if not expected:
                    msg = ("Action %s expects no parameters" % (self.name, ))
                else:
                    msg = ("Action %s does not expect parameter(s): %s"
                           % (self.name, ", ".join(unknown)))
                raise UnknownParameters(msg, params=unknown)

            param_index = dict([(p.name, p) for p in parameters])
            validated = {}
            errors = {}
            for param_name, param_value in kwargs.iteritems():
                info = param_index[param_name].value_info
                try:
                    valval = IValidator(info).validate(param_value)
                    validated[param_name] = valval
                except ValueError, e:
                    errors[param_name] = e
                except MissingParameters, e:
                    missings = ['.'.join([param_name, x])
                                for x in e.parameters]
                    msg = ("Action %s is missing parameter(s): %s"
                           % (self.name, ", ".join(missings)))
                    raise MissingParameters(msg, params=missings)
                except UnknownParameters, e:
                    unknown = ['.'.join([param_name, x]) for x in e.parameters]
                    msg = ("Action %s is missing parameter(s): %s"
                           % (self.name, ", ".join(unknown)))
                    raise UnknownParameters(msg, params=unknown)
                except InvalidParameters, e:
                    params = self._prepend_name(param_name, e.reasons)
                    errors.update(params)

            if errors:
                param_errors = ", ".join("%s: %s" % (p, m)
                                         for p, m in errors.iteritems())
                msg = ("Action %s parameter(s) invalid: %s"
                       % (self.name, param_errors))
                raise InvalidParameters(msg, params=errors)

            for param in parameters:
                if not param.is_required:
                    info = param.value_info
                    if param.name not in validated and info.use_default:
                        validated[param.name] = info.default

            value = validated.pop(u"value", None)

            # We use the model name instead of the action name as key
            maker = IContextMaker(self.model)
            context = maker.make_context(action=self)

            def log_effect_Error(failure, effect):
                error.handle_failure(None, failure,
                                     "Failure during effect %s execution",
                                     effect.func_name)
                return failure

            for effect in self._effects:
                try:
                    d.addCallback(effect, context, **validated)
                    d.addErrback(log_effect_Error, effect)
                except AssertionError:
                    err = ValueError("Invalid action effect: %r" % (effect, ))
                    failure = Failure(err, exc_tb=sys.exc_info()[2])
                    return defer.fail(failure)

            if self._result_info is not None:
                d.addCallback(IValidator(self._result_info).publish)
            else:
                d.addCallback(defer.override_result, None)

        except:
            return defer.fail()

        else:
            d.callback(value)
            return d

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
        cls._category = ActionCategories(category)

    @classmethod
    def annotate_is_idempotent(cls, is_idempotent=True):
        """@see: feat.models.action.is_idempotent"""
        cls._is_idempotent = bool(is_idempotent)

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
    def annotate_value(cls, value_info, label=None, desc=None):
        """@see: feat.models.action.value"""
        param = Param(u"value", value_info, is_required=True,
                      label=label, desc=desc)
        cls._parameters.append(param)

    @classmethod
    def annotate_param(cls, name, value_info, is_required=True,
                       label=None, desc=None):
        """@see: feat.models.action.parameter"""
        name = _validate_str(name)
        param = Param(name, value_info, is_required=is_required,
                      label=label, desc=desc)
        cls._parameters.append(param)

    @classmethod
    def annotate_param_instance(cls, param):
        cls._parameters.append(param)

    @classmethod
    def annotate_effect(cls, effect):
        """@see: feat.models.action.effect"""
        cls._effects.append(effect)

    ### privvate ###

    def _prepend_name(self, prefix, dict_):
        '''changes the keys of the dictionary prepending them with "name."'''
        return dict(['.'.join([prefix, name]), msg]
                    for name, msg in dict_.iteritems())

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
